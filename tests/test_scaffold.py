from custom_components.entity_rename_safe.const import DEFAULT_EXCLUDES, DOMAIN, WORK_DIR_NAME


def test_domain_constants() -> None:
    assert DOMAIN == "entity_rename_safe"
    assert WORK_DIR_NAME == ".entity_rename_safe"
    for excluded in (".storage", ".git", "custom_components", "secrets.yaml"):
        assert excluded in DEFAULT_EXCLUDES


async def test_integration_setup_loads(hass) -> None:  # type: ignore[no-untyped-def]
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
