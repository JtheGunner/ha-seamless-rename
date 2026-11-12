"""Reload the Home Assistant domains whose YAML files an apply changed."""

from collections.abc import Collection

from homeassistant.core import HomeAssistant

RELOAD_SERVICE = "reload"
_DOMAIN_BY_STEM = {
    "automations": "automation",
    "scripts": "script",
    "scenes": "scene",
    "groups": "group",
    "templates": "template",
}


def domains_for_files(relative_paths: Collection[str]) -> tuple[set[str], bool]:
    """Map changed YAML files to reloadable domains.

    Returns the domains and whether some file has no known domain, in which case only a
    restart is certain to pick the change up.
    """
    domains: set[str] = set()
    unknown = False
    for path in relative_paths:
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        domain = _DOMAIN_BY_STEM.get(stem)
        if domain is None:
            unknown = True
        else:
            domains.add(domain)
    return domains, unknown


async def reload_domains(hass: HomeAssistant, domains: Collection[str]) -> list[str]:
    """Call ``<domain>.reload`` for each domain and return those that have no such service.

    The returned domains need a Home Assistant restart to apply the change.
    """
    restart_required: list[str] = []
    for domain in sorted(domains):
        if not hass.services.has_service(domain, RELOAD_SERVICE):
            restart_required.append(domain)
            continue
        await hass.services.async_call(domain, RELOAD_SERVICE, blocking=True)
    return restart_required
