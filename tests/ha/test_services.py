import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component

from custom_components.seamless_rename.const import DOMAIN
from custom_components.seamless_rename.ha import api

from .conftest import add_entity


async def _call(hass: HomeAssistant, service: str, data: dict) -> dict:
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def test_plan_apply_undo_through_services(
    hass: HomeAssistant, config_dir: Path, check_ok: None
) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    add_entity(hass, "sensor.foo")
    (config_dir / "a.yaml").write_text("entity_id: sensor.foo\n")

    plan = await _call(hass, "plan", {"from": "sensor.foo", "to": "sensor.bar"})
    assert plan["blockers"] == []
    applied = await _call(hass, "apply", {"plan_id": plan["plan_id"]})
    assert applied["status"] == "completed"
    assert (config_dir / "a.yaml").read_text() == "entity_id: sensor.bar\n"
    undone = await _call(hass, "undo", {"apply_id": applied["apply_id"]})
    assert undone["status"] == "undone"
    assert (config_dir / "a.yaml").read_text() == "entity_id: sensor.foo\n"


async def test_services_are_admin_only_and_return_responses(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    for service in ("plan", "apply", "undo"):
        assert hass.services.has_service(DOMAIN, service)


async def test_plan_rejects_from_without_to(hass: HomeAssistant, config_dir: Path) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError):
        await _call(hass, "plan", {"from": "sensor.foo"})


async def test_plan_rejects_pattern_with_from(hass: HomeAssistant, config_dir: Path) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError):
        await _call(
            hass,
            "plan",
            {"from": "sensor.a", "to": "sensor.b", "pattern": {"match": "a", "replace": "b"}},
        )


async def test_apply_error_becomes_validation_error(hass: HomeAssistant, config_dir: Path) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError):
        await _call(hass, "apply", {"plan_id": "plan-missing"})


async def test_service_errors_are_translatable(hass: HomeAssistant, config_dir: Path) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError) as rename_error:
        await _call(hass, "apply", {"plan_id": "plan-missing"})
    assert rename_error.value.translation_domain == DOMAIN
    assert rename_error.value.translation_key == "plan_not_found"
    assert "plan-missing" in rename_error.value.translation_placeholders["error"]

    with pytest.raises(ServiceValidationError) as value_error:
        await _call(
            hass,
            "plan",
            {"from": "sensor.a", "to": "sensor.b", "pattern": {"match": "a", "replace": "b"}},
        )
    assert value_error.value.translation_domain == DOMAIN
    assert value_error.value.translation_key == "invalid_request"


async def test_every_error_code_has_an_exception_translation() -> None:
    codes = {api.RenameError.code}
    codes.update(
        cls.code
        for cls in vars(api).values()
        if isinstance(cls, type) and issubclass(cls, api.RenameError)
    )
    codes.add("invalid_request")
    translations = Path(__file__).parents[2] / "custom_components/seamless_rename/translations"
    for language in ("en", "de"):
        exceptions = json.loads((translations / f"{language}.json").read_text())["exceptions"]
        assert codes <= set(exceptions), language
        assert all("{error}" in item["message"] for item in exceptions.values()), language
