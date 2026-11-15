# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-15

First release.

### Added

- Rename one or many entity IDs and rewrite every consumer in one step: YAML files and packages,
  storage-mode dashboards, UI helpers and config-entry helpers (SQL, history stats).
- Plan, apply and undo with a dry-run diff, backups, a configuration check after the edit and a
  full rollback on any failure. A repair issue reports an apply that was interrupted by a crash.
- Bulk renames by pattern or by a list of `from,to` pairs, with collision and blocker detection.
- Read-only audit of references to entities that do not exist, and a references view that shows
  every consumer of one entity.
- Confidence levels (`certain`, `likely`, `uncertain`) per hit; uncertain hits are off by default.
- Warnings for Jinja templates that build entity IDs dynamically.
- Optional external search folders (Node-RED, pyscript, AppDaemon, Grafana); hits are reported,
  never edited.
- Admin-only services, a websocket API and a sidebar panel with single rename, preview, bulk and
  history.
- English and German texts for the panel, the setup and options dialogs, services, errors and the
  repair issue.
- Option to hide the sidebar panel (**Settings → Devices & services → Seamless Rename →
  Configure**); it applies without a restart.

### Fixed

- The panel scripts are served under a content-hash URL, so a browser never keeps an outdated
  copy after an update, and they are read outside the event loop.
- Stray `null` text in the panel.
- Editor history, tool backups and macOS metadata files are skipped when scanning.

[0.1.0]: https://github.com/JtheGunner/ha-seamless-rename/releases/tag/v0.1.0
