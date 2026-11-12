from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.seamless_rename.const import DOMAIN

from .conftest import add_entity


async def test_non_admin_rejected(
    hass: HomeAssistant, hass_ws_client, hass_read_only_access_token: str
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass, hass_read_only_access_token)
    payloads = {
        "plan": {"from": "sensor.foo", "to": "sensor.bar"},
        "apply": {"plan_id": "p"},
        "undo": {"apply_id": "a"},
        "history": {},
        "audit": {},
        "references": {"entity_id": "sensor.foo"},
    }
    for message_id, (command, payload) in enumerate(payloads.items(), start=1):
        await client.send_json({"id": message_id, "type": f"{DOMAIN}/{command}", **payload})
        response = await client.receive_json()
        assert response["success"] is False
        assert response["error"]["code"] == "unauthorized"


async def test_plan_roundtrip_through_websocket(
    hass: HomeAssistant, hass_ws_client, config_dir: Path, check_ok: None
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    add_entity(hass, "sensor.foo")
    (config_dir / "a.yaml").write_text("entity_id: sensor.foo\n")
    client = await hass_ws_client(hass)

    await client.send_json(
        {"id": 1, "type": f"{DOMAIN}/plan", "from": "sensor.foo", "to": "sensor.bar"}
    )
    plan = (await client.receive_json())["result"]
    assert plan["blockers"] == []
    assert "sensor.bar" in plan["diff"]

    await client.send_json({"id": 2, "type": f"{DOMAIN}/apply", "plan_id": plan["plan_id"]})
    applied = (await client.receive_json())["result"]
    assert applied["status"] == "completed"
    assert (config_dir / "a.yaml").read_text() == "entity_id: sensor.bar\n"

    await client.send_json({"id": 3, "type": f"{DOMAIN}/undo", "apply_id": applied["apply_id"]})
    assert (await client.receive_json())["result"]["status"] == "undone"
    assert (config_dir / "a.yaml").read_text() == "entity_id: sensor.foo\n"


async def test_rename_error_is_reported_to_client(
    hass: HomeAssistant, hass_ws_client, config_dir: Path
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/apply", "plan_id": "missing"})
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "rename_rejected"
    assert response["error"]["translation_key"] == "plan_not_found"
    assert response["error"]["translation_domain"] == DOMAIN


async def test_plan_messages_come_with_codes_for_the_client(
    hass: HomeAssistant, hass_ws_client, config_dir: Path
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    add_entity(hass, "sensor.a")
    add_entity(hass, "sensor.b")
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": f"{DOMAIN}/plan",
            "renames": [
                {"from": "sensor.a", "to": "sensor.a2"},
                {"from": "sensor.b", "to": "sensor.a2"},
            ],
        }
    )
    plan = (await client.receive_json())["result"]
    assert plan["blocker_details"] == [
        {"code": "duplicate_target", "params": {"entity": "sensor.a2"}}
    ]
    assert len(plan["blocker_details"]) == len(plan["blockers"])
    assert len(plan["warning_details"]) == len(plan["warnings"])


async def test_plan_without_target_is_invalid_request(
    hass: HomeAssistant, hass_ws_client, config_dir: Path
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/plan", "from": "sensor.foo"})
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "invalid_request"


async def test_history_lists_manifests_newest_first(
    hass: HomeAssistant, hass_ws_client, config_dir: Path, check_ok: None
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    add_entity(hass, "sensor.a")
    add_entity(hass, "sensor.c")
    client = await hass_ws_client(hass)
    ids = []
    for index, (old, new) in enumerate((("sensor.a", "sensor.b"), ("sensor.c", "sensor.d"))):
        await client.send_json(
            {"id": 10 + index * 2, "type": f"{DOMAIN}/plan", "from": old, "to": new}
        )
        plan = (await client.receive_json())["result"]
        await client.send_json(
            {"id": 11 + index * 2, "type": f"{DOMAIN}/apply", "plan_id": plan["plan_id"]}
        )
        ids.append((await client.receive_json())["result"]["apply_id"])

    await client.send_json({"id": 20, "type": f"{DOMAIN}/history"})
    history = (await client.receive_json())["result"]["history"]
    assert [item["apply_id"] for item in history] == list(reversed(ids))
    assert history[0]["renames"] == [{"from": "sensor.c", "to": "sensor.d"}]


async def test_history_skips_unreadable_manifest(
    hass: HomeAssistant, hass_ws_client, config_dir: Path
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    broken = config_dir / ".seamless_rename" / "backups" / "x"
    broken.mkdir(parents=True)
    (broken / "manifest.json").write_text("not json")
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/history"})
    assert (await client.receive_json())["result"] == {"history": []}


async def test_audit_and_references_through_websocket(
    hass: HomeAssistant, hass_ws_client, config_dir: Path
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    add_entity(hass, "sensor.foo")
    (config_dir / "a.yaml").write_text("entity_id: sensor.foo\nother: sensor.gone\n")
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/audit"})
    assert "sensor.gone" in (await client.receive_json())["result"]["dead"]
    await client.send_json({"id": 2, "type": f"{DOMAIN}/references", "entity_id": "sensor.foo"})
    refs = (await client.receive_json())["result"]["references"]
    assert refs[0]["file"].endswith("a.yaml")


async def test_apply_without_plan_id_is_invalid_format(
    hass: HomeAssistant, hass_ws_client, config_dir: Path
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": f"{DOMAIN}/apply"})
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "invalid_format"


async def test_plan_rejects_pattern_combined_with_from(
    hass: HomeAssistant, hass_ws_client, config_dir: Path
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": f"{DOMAIN}/plan",
            "from": "sensor.a",
            "to": "sensor.b",
            "pattern": {"match": "a", "replace": "b"},
        }
    )
    response = await client.receive_json()
    assert response["success"] is False
    assert response["error"]["code"] == "invalid_request"


async def test_exclude_and_include_uncertain_through_websocket(
    hass: HomeAssistant, hass_ws_client, config_dir: Path, check_ok: None
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    add_entity(hass, "sensor.foo")
    target = config_dir / "a.yaml"
    target.write_text("entity_id: sensor.foo\n# sensor.foo in a comment\n")
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": f"{DOMAIN}/plan",
            "from": "sensor.foo",
            "to": "sensor.bar",
            "include_uncertain": True,
        }
    )
    plan = (await client.receive_json())["result"]
    assert [row["selected"] for row in plan["findings"]] == [True, True]
    comment = next(row for row in plan["findings"] if row["confidence"] == "uncertain")

    await client.send_json(
        {
            "id": 2,
            "type": f"{DOMAIN}/apply",
            "plan_id": plan["plan_id"],
            "exclude": [comment["finding_id"]],
        }
    )
    assert (await client.receive_json())["result"]["status"] == "completed"
    assert target.read_text() == "entity_id: sensor.bar\n# sensor.foo in a comment\n"


async def test_plan_accepts_a_list_of_renames(
    hass: HomeAssistant, hass_ws_client, config_dir: Path
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    add_entity(hass, "sensor.a")
    add_entity(hass, "sensor.b")
    client = await hass_ws_client(hass)
    await client.send_json(
        {
            "id": 1,
            "type": f"{DOMAIN}/plan",
            "renames": [
                {"from": "sensor.a", "to": "sensor.a2"},
                {"from": "sensor.b", "to": "sensor.a2"},
            ],
        }
    )
    plan = (await client.receive_json())["result"]
    assert len(plan["renames"]) == 2
    assert any("more than one rename" in blocker for blocker in plan["blockers"])
