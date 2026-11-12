<div align="center">

# 🏷️ Entity Rename Safe

**Rename a Home Assistant entity — and every place that uses it.**
Dry-run first, one-click undo, no half-renamed config.

<code>🔍 scan config</code> &nbsp;→&nbsp; <code>📝 dry-run diff</code> &nbsp;→&nbsp; <code>✅ apply</code> &nbsp;→&nbsp; <code>↩️ undo</code>

![License](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square)
![Python](https://img.shields.io/badge/python-3.14-3776ab?style=flat-square&logo=python&logoColor=white)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.10%2B-0ea5e9?style=flat-square&logo=homeassistant&logoColor=white)
![HACS](https://img.shields.io/badge/HACS-custom-f59e0b?style=flat-square)
![Telemetry](https://img.shields.io/badge/telemetry-none-8b5cf6?style=flat-square)

</div>

---

## 🎯 What it is

Home Assistant renames only the registry entry. Every reference in YAML, templates,
dashboards and helpers silently turns into a dead ID.

**Entity Rename Safe** closes that gap. It renames one or many entity IDs and rewrites
every consumer it can find, in one safe step:

|    | Step        | What happens                                                                              |
|:--:|-------------|-------------------------------------------------------------------------------------------|
| 🔍 | **Plan**    | Scans the configuration and shows the exact diff. Nothing is written.                     |
| ✅ | **Apply**   | Backs up, rewrites the planned text spans, renames in the registry, reloads what it can.  |
| ↩️ | **Undo**    | Restores files, dashboards, helpers and entity IDs of any completed apply.                |
| 🩺 | **Audit**   | Lists references to entities that do not exist (read-only).                               |
| 🔗 | **References** | Shows every consumer of one entity — "what would break?" (read-only).                |

It works with and without GitOps. Safety (backup, undo) never depends on git.

### ✨ At a glance

|                                |                                                                                          |
|--------------------------------|------------------------------------------------------------------------------------------|
| 📝&nbsp;&nbsp;**Exact edits**  | Only the planned text spans change. No re-formatting, comments stay, YAML is never re-serialised. |
| 🛡️&nbsp;&nbsp;**Safe**         | Config check after the edit, full rollback on any failure, nothing is written to `.storage`. |
| 🎚️&nbsp;&nbsp;**Confidence**   | Each hit is `certain`, `likely` or `uncertain`. Uncertain hits (for example comments) are off by default. |
| 🧩&nbsp;&nbsp;**Everywhere**   | YAML files, packages, storage-mode dashboards, UI helpers, plus optional external folders (report only). |
| 🖥️&nbsp;&nbsp;**Two front ends** | Admin-only services (usable from automations or MCP) and a sidebar panel.              |

---

## 📦 Installation

### HACS (custom repository)

1. In HACS open **⋮ → Custom repositories**.
2. Add `https://github.com/JtheGunner/ha-seamless-rename` with category **Integration**.
3. Install **Entity Rename Safe** and restart Home Assistant.

### Manual

Copy `custom_components/entity_rename_safe/` into the `custom_components/` folder of your
Home Assistant configuration and restart.

### Set up

1. Go to **Settings → Devices & services → Add integration → Entity Rename Safe**.
2. Optional: open the integration's **Configure** dialog and list absolute folders
   (for example a Node-RED or AppDaemon folder). They are searched and reported, never changed.

> [!IMPORTANT]
> The integration keeps plans and backups in `/config/.entity_rename_safe/`.
> If your configuration lives in git, add this line to its `.gitignore`:
>
> ```gitignore
> .entity_rename_safe/
> ```
>
> The integration never edits `.gitignore` itself.

---

## 🚀 Usage

All services are admin-only and return a response. Try them in
**Developer tools → Actions** with *Return response* switched on.

### 1. Plan (dry-run)

Single entity:

```yaml
action: entity_rename_safe.plan
data:
  from: sensor.living_room_temp
  to: sensor.living_room_temperature
```

Several explicit renames, or a pattern resolved against the registry:

```yaml
action: entity_rename_safe.plan
data:
  renames:
    - { from: media_player.kitchen, to: media_player.kitchen_speaker }
    - { from: media_player.hall, to: media_player.hall_speaker }
```

```yaml
action: entity_rename_safe.plan
data:
  pattern: { match: "^media_player\\.old_(.*)$", replace: "media_player.new_\\1", domain: media_player }
```

The response contains the `plan_id`, the resolved `renames`, `blockers`, `warnings`, a
`summary` per file, dashboard and helper, the `findings` (each with a `finding_id` and its
confidence) and `external` hits. A plan with blockers cannot be applied. Plans expire after 24 hours.

| Field                | Meaning                                                                 |
|----------------------|-------------------------------------------------------------------------|
| `include_uncertain`  | Also rewrite uncertain hits. Default `false`.                           |

### 2. Apply

```yaml
action: entity_rename_safe.apply
data:
  plan_id: plan-0123456789ab
  exclude: []   # optional finding IDs from the plan to leave untouched
```

Apply verifies that nothing changed since the plan, writes a backup, edits the files, runs the
configuration check, renames the entities, updates dashboards and helpers, and reloads the
affected domains. The response sets `restart_required: true` when a domain has no reload service
or a reload fails. Any failure before that point rolls everything back.

### 3. Undo

```yaml
action: entity_rename_safe.undo
data:
  apply_id: apply-20261112T031500-1a2b3c
  force: false
```

Undo is refused if a touched file changed after the apply. `force: true` overrides that and
overwrites later edits.

### 4. Audit and references

```yaml
action: entity_rename_safe.audit
```

```yaml
action: entity_rename_safe.references
data:
  entity_id: sensor.living_room_temperature
```

### 🖥️ Panel

The **Entity Rename** entry in the sidebar (administrators only) offers the same functions:

- **Single rename** with entity picker and live validation of the new ID.
- **Preview** with the diff, findings grouped by file, dashboard or helper, and a checkbox per finding.
- **Bulk** by pattern or pasted `from,to` lines, with a table that marks collisions.
- **History** of all applies with undo.

### 🩹 Interrupted apply

If Home Assistant stops in the middle of an apply, a repair issue appears after the next start
and offers to undo the half-finished rename.

---

## 🧠 How it works

```text
 plan ──► scan YAML · dashboards · helpers ──► diff + findings (stored, nothing written)
   │
 apply ─► verify hashes ─► backup ─► write files ─► config check ─► registry rename
                                                       │                  │
                                              restore files        dashboards · helpers
                                                                          │
                                                                  reload · verify
```

- IDs are matched with word boundaries, longest first, in a single pass: renaming `a → b` and
  `b → c` never turns `a` into `c`. Swaps use a temporary ID.
- Dashboards and helpers are changed through Home Assistant's own APIs, never by editing `.storage`.
- If Home Assistant changes these internal APIs, the affected adapter falls back to **report-only**
  and says so in the plan warnings.

---

## ⚠️ Known limits

- **Dynamically built IDs** (string concatenation, `selectattr` patterns) cannot be resolved.
  They are reported as warnings.
- **YAML entities without `unique_id`** are not in the registry and cannot be renamed. The plan
  blocks with a pointer to the definition.
- **Custom integrations that store IDs in config entry `data`** are reported, not changed.
- **External systems** (Node-RED, AppDaemon, pyscript, Grafana) are searched in the configured
  folders and reported only.
- Entities whose object ID equals a file extension word (such as `sensor.log`) can be missed
  by the audit, because file names like `home.log` look the same.
- `friendly_name` is never changed, and no alias for the old ID is created.

---

## 🛠️ Development

```bash
uv sync
uv run pytest                 # Python tests (engine tests need no Home Assistant)
node --test "tests/panel/*.test.mjs"   # panel component tests
uv run ruff check . && uv run ruff format --check .
uv run mypy custom_components
```

Layout:

| 📁 | Path                                      | Role                                               |
|:--:|-------------------------------------------|----------------------------------------------------|
| 🧮 | `custom_components/entity_rename_safe/engine/` | Pure logic, never imports Home Assistant       |
| 🔌 | `custom_components/entity_rename_safe/ha/`     | Adapters for registry, files, dashboards, helpers; `api.py` is the one entry point |
| 📡 | `services.py`, `websocket.py`                  | Thin wrappers over `ha/api.py`                  |
| 🖼️ | `panel/`                                       | Vanilla web component, no build step           |

An optional end-to-end test runs against a real Home Assistant container: `E2E=1 uv run pytest tests/e2e`.

---

## 🤝 Contributing

Issues and pull requests are welcome at
[github.com/JtheGunner/ha-seamless-rename](https://github.com/JtheGunner/ha-seamless-rename/issues).
Please include a test with every behaviour change, keep test fixtures anonymised, and run the
commands in the Development section before opening a pull request.

---

## 📄 License

[MIT](LICENSE)

---

<div align="center"><sub>Rename with confidence — and keep an undo button. 🏷️</sub></div>
