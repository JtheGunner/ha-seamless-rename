from pathlib import Path

import probatio
import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.seamless_rename.const import DOMAIN, WORK_DIR_NAME
from custom_components.seamless_rename.engine.models import Confidence
from custom_components.seamless_rename.ha import api

from .conftest import add_entity

AUTOMATION = (
    "- alias: Demo\n"
    "  trigger:\n"
    "    - platform: state\n"
    "      entity_id: sensor.ghost\n"
    "  action:\n"
    "    - service: light.turn_on\n"
    "      target: {entity_id: sensor.real}\n"
)


async def _noop(call: ServiceCall) -> None:
    return None


async def test_audit_finds_dead_reference(hass: HomeAssistant, config_dir: Path) -> None:
    add_entity(hass, "sensor.real")
    (config_dir / "automations.yaml").write_text(AUTOMATION)

    report = await api.audit(hass)

    assert list(report.dead) == ["sensor.ghost"]
    finding = report.dead["sensor.ghost"][0]
    assert (finding.location, finding.line) == ("automations.yaml", 4)
    assert finding.confidence is Confidence.CERTAIN


async def test_audit_ignores_existing_entities_and_services(
    hass: HomeAssistant, config_dir: Path
) -> None:
    add_entity(hass, "sensor.real")
    add_entity(hass, "light.lamp")
    hass.services.async_register("light", "turn_on", _noop)
    (config_dir / "a.yaml").write_text(
        "a: sensor.real\nb: light.turn_on\nc: light.lamp\nd: unknown_domain.thing\n"
    )
    report = await api.audit(hass)
    assert report.dead == {}


async def test_audit_ignores_excluded_files(hass: HomeAssistant, config_dir: Path) -> None:
    add_entity(hass, "sensor.real")
    (config_dir / "secrets.yaml").write_text("k: sensor.ghost\n")
    assert (await api.audit(hass)).dead == {}


async def test_references_lists_file_and_line(hass: HomeAssistant, config_dir: Path) -> None:
    add_entity(hass, "sensor.real")
    (config_dir / "automations.yaml").write_text(AUTOMATION)
    (config_dir / "other.yaml").write_text("x: 1\ny: sensor.real\n")

    found = await api.references(hass, "sensor.real")

    assert [(f.location, f.line) for f in found] == [("automations.yaml", 7), ("other.yaml", 2)]


async def test_references_rejects_invalid_id(hass: HomeAssistant, config_dir: Path) -> None:
    with pytest.raises(ValueError, match="not a valid"):
        await api.references(hass, "Not An Id")


async def test_both_do_not_write_anything(hass: HomeAssistant, config_dir: Path) -> None:
    add_entity(hass, "sensor.real")
    target = config_dir / "automations.yaml"
    target.write_text(AUTOMATION)
    before = target.read_bytes()
    registry_before = set(er.async_get(hass).entities)

    await api.audit(hass)
    await api.references(hass, "sensor.real")

    assert target.read_bytes() == before
    assert set(er.async_get(hass).entities) == registry_before
    assert sorted(path.name for path in config_dir.iterdir()) == ["automations.yaml"]
    assert not (config_dir / WORK_DIR_NAME).exists()


async def test_services_return_reports(hass: HomeAssistant, config_dir: Path) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    add_entity(hass, "sensor.real")
    (config_dir / "automations.yaml").write_text(AUTOMATION)

    audit = await hass.services.async_call(DOMAIN, "audit", {}, blocking=True, return_response=True)
    assert audit["dead"]["sensor.ghost"][0]["line"] == 4
    refs = await hass.services.async_call(
        DOMAIN, "references", {"entity_id": "sensor.real"}, blocking=True, return_response=True
    )
    assert refs["references"][0]["file"] == "automations.yaml"
    with pytest.raises(probatio.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "references",
            {"entity_id": "sensor.Bad Id"},
            blocking=True,
            return_response=True,
        )


async def test_audit_ignores_file_names_and_reports_weaker_hits(
    hass: HomeAssistant, config_dir: Path
) -> None:
    add_entity(hass, "sensor.real")
    add_entity(hass, "light.lamp")
    (config_dir / "a.yaml").write_text(
        "sensor: !include sensor.yaml\n"
        "light: !include packages/light.yml\n"
        "t: \"{{ states('sensor.ghost_jinja') }}\"\n"
        "# note: sensor.ghost_comment\n"
    )
    report = await api.audit(hass)
    assert sorted(report.dead) == ["sensor.ghost_comment", "sensor.ghost_jinja"]
    assert report.dead["sensor.ghost_jinja"][0].confidence is Confidence.LIKELY
    assert report.dead["sensor.ghost_comment"][0].confidence is Confidence.UNCERTAIN
