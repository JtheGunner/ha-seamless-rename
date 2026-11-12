"""Constants for the seamless_rename integration."""

DOMAIN = "seamless_rename"
WORK_DIR_NAME = ".seamless_rename"
CONF_EXTERNAL_PATHS = "external_paths"
CONF_SHOW_PANEL = "show_panel"
DATA_PANEL_URL = "panel_url"

MAX_EXTERNAL_FILE_BYTES = 2 * 1024 * 1024
MAX_EXTERNAL_HITS = 500

DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".storage",
    ".git",
    "custom_components",
    "deps",
    ".cloud",
    WORK_DIR_NAME,
    "secrets.yaml",
    # Editor history, tool backups and macOS AppleDouble files are copies, not live config.
    ".vscode",
    ".idea",
    ".ha_mcp",
    "._*",
)

# Folders and files never searched in external paths: the usual excludes plus tool folders and
# Node-RED credential files, so secrets cannot end up in a plan.
EXTERNAL_EXCLUDES: tuple[str, ...] = (
    *DEFAULT_EXCLUDES,
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "*_cred.json",
)
