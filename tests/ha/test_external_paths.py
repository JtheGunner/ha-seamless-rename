from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.entity_rename_safe.const import (
    CONF_EXTERNAL_PATHS,
    DOMAIN,
    MAX_EXTERNAL_HITS,
)
from custom_components.entity_rename_safe.engine.models import Rename
from custom_components.entity_rename_safe.ha import api
from custom_components.entity_rename_safe.ha.api import PlanRequest

from .conftest import add_entity


def _own_entry(hass: HomeAssistant, paths: list[str]) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_EXTERNAL_PATHS: paths})
    entry.add_to_hass(hass)
    return entry


async def _plan(hass: HomeAssistant) -> api.PlanResult:
    return await api.plan(hass, PlanRequest(renames=(Rename("sensor.foo", "sensor.bar"),)))


async def test_external_path_hits_reported_not_edited(
    hass: HomeAssistant, config_dir: Path, tmp_path: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    external = tmp_path / "node-red"
    (external / "node_modules").mkdir(parents=True)
    flows = external / "flows.json"
    flows.write_text('[\n  {"entity": "sensor.foo"},\n  {"other": "sensor.foo_2"}\n]\n')
    (external / "node_modules" / "skipped.js").write_text("sensor.foo")
    (external / "blob.bin").write_bytes(b"\0sensor.foo")
    _own_entry(hass, [str(external), str(tmp_path / "missing")])

    plan = await _plan(hass)

    assert [(h.path, h.line, h.text) for h in plan.external] == [
        (str(flows), 2, '{"entity": "sensor.foo"},')
    ]
    assert plan.summary["external"] == 1
    assert any("missing" in w for w in plan.warnings)
    before = flows.read_bytes()

    await api.apply(hass, plan.plan_id)

    assert flows.read_bytes() == before


async def test_no_external_paths_configured(hass: HomeAssistant, config_dir: Path) -> None:
    add_entity(hass, "sensor.foo")
    plan = await _plan(hass)
    assert plan.external == []
    assert plan.summary["external"] == 0


async def test_external_hits_are_capped(
    hass: HomeAssistant, config_dir: Path, tmp_path: Path
) -> None:
    add_entity(hass, "sensor.foo")
    external = tmp_path / "ext"
    external.mkdir()
    (external / "big.txt").write_text("sensor.foo\n" * (MAX_EXTERNAL_HITS + 20))
    _own_entry(hass, [str(external)])
    plan = await _plan(hass)
    assert len(plan.external) == MAX_EXTERNAL_HITS
    assert any("cut off" in w for w in plan.warnings)


async def test_google_assistant_yaml_filter_rewritten(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    target = config_dir / "configuration.yaml"
    target.write_text(
        "google_assistant:\n"
        "  project_id: demo\n"
        "  entity_config:\n"
        "    sensor.foo:\n"
        "      name: Foo\n"
        "  exposed_domains: [sensor]\n"
        "homekit:\n"
        "  filter:\n"
        "    include_entities:\n"
        "      - sensor.foo\n"
    )
    await api.apply(hass, (await _plan(hass)).plan_id)
    text = target.read_text()
    assert "    sensor.bar:\n      name: Foo\n" in text
    assert "      - sensor.bar\n" in text
    assert "sensor.foo" not in text


async def test_sql_and_history_stats_options_rewritten_via_helper_adapter(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    add_entity(hass, "sensor.foo")
    sql = MockConfigEntry(
        domain="sql",
        options={"query": "SELECT state FROM states WHERE entity_id = 'sensor.foo'", "name": "x"},
    )
    history = MockConfigEntry(
        domain="history_stats",
        options={"entity_id": "sensor.foo", "state": ["on"], "type": "time"},
    )
    sql.add_to_hass(hass)
    history.add_to_hass(hass)

    result = await api.apply(hass, (await _plan(hass)).plan_id)

    assert sorted(result.changed_helpers) == sorted([sql.entry_id, history.entry_id])
    assert sql.options["query"] == "SELECT state FROM states WHERE entity_id = 'sensor.bar'"
    assert history.options["entity_id"] == "sensor.bar"


async def test_options_flow_stores_absolute_paths_only(hass: HomeAssistant, tmp_path: Path) -> None:
    entry = _own_entry(hass, [])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    bad = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_EXTERNAL_PATHS: ["relative/dir"]}
    )
    assert bad["errors"] == {"base": "invalid_path"}

    good = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_EXTERNAL_PATHS: [f" {tmp_path} ", ""]}
    )
    assert good["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXTERNAL_PATHS] == [str(tmp_path)]


async def test_symlinks_fifos_oversized_and_secret_files_are_not_read(
    hass: HomeAssistant, config_dir: Path, tmp_path: Path
) -> None:
    import os

    from custom_components.entity_rename_safe.const import MAX_EXTERNAL_FILE_BYTES

    add_entity(hass, "sensor.foo")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("sensor.foo")
    external = tmp_path / "ext"
    (external / ".storage").mkdir(parents=True)
    (external / "linked_dir").symlink_to(outside, target_is_directory=True)
    (external / "linked_file.txt").symlink_to(outside / "secret.txt")
    os.mkfifo(external / "pipe.txt")
    (external / "huge.txt").write_text("sensor.foo " + "x" * MAX_EXTERNAL_FILE_BYTES)
    (external / ".storage" / "core.txt").write_text("sensor.foo")
    (external / "secrets.yaml").write_text("k: sensor.foo")
    (external / "flows_cred.json").write_text('{"sensor.foo": "token"}')
    (external / "ok.txt").write_text("sensor.foo\n")
    _own_entry(hass, [str(external)])

    plan = await _plan(hass)

    assert [Path(h.path).name for h in plan.external] == ["ok.txt"]


async def test_options_flow_rejects_missing_and_protected_folders(
    hass: HomeAssistant, config_dir: Path, tmp_path: Path
) -> None:
    (config_dir / ".storage").mkdir()
    entry = _own_entry(hass, [])
    result = await hass.config_entries.options.async_init(entry.entry_id)

    missing = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_EXTERNAL_PATHS: [str(tmp_path / "nope")]}
    )
    assert missing["errors"] == {"base": "not_a_directory"}

    protected = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_EXTERNAL_PATHS: [str(config_dir / ".storage")]}
    )
    assert protected["errors"] == {"base": "protected_path"}
