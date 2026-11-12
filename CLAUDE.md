# ha-seamless-rename (entity_rename_safe)

Home Assistant custom integration that renames entity IDs and rewrites all consumers (YAML, UI dashboards, UI helpers) with dry-run, rollback, and undo. Design and plan live in `docs/superpowers/` (git-ignored, local only). Read the spec before changing behaviour.

## Hard rules (project-specific)

- `custom_components/entity_rename_safe/engine/` must **never import Home Assistant**. Pure logic only.
- Services and websocket are thin wrappers over `ha/api.py`. No logic in `services.py`, `websocket.py`, or `panel/`.
- **Never write into `.storage`, `secrets.yaml`, or `custom_components`.** Dashboards and helpers go through HA APIs only.
- Edit YAML by **span replacement in the source text**. Never re-serialise a YAML file.
- Match entity IDs with the shared token pattern in `engine/ids.py`. Do not write ad-hoc regexes elsewhere.
- Plan state lives in `/config/.entity_rename_safe/` (plans, backups). It is not part of the repo.

## Naming exceptions

- Service fields are `from` / `to`; in Python they are `from_id` / `to_id`.
- The integration domain is `entity_rename_safe`; the repo name is `ha-seamless-rename`.

## Commands

- Tests: `pytest` (engine tests need no HA; HA tests use `pytest-homeassistant-custom-component`).
- Panel component tests: `node --test "tests/panel/*.test.mjs"` (no build chain, no dependencies).
- Lint and types: `ruff check .` and `mypy custom_components`.

## Working with the plan

- Each `### T<n>` section in the plan is one YouTrack ticket. Create and work them with the `youtrack-task` skill, in dependency order.
- Test fixtures must be anonymised. Do not commit real entity names, tokens, or content from the author's live instance.

## Live instance access

The author's HA instance is reachable read-only through the `home-assistant` MCP server. Use it for investigation only. Do not call write tools (rename, set, remove, reload, restart) against it unless explicitly asked.
