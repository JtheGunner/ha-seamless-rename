"""Constants for the entity_rename_safe integration."""

DOMAIN = "entity_rename_safe"
WORK_DIR_NAME = ".entity_rename_safe"
CONF_EXTERNAL_PATHS = "external_paths"

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
