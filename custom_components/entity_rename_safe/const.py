"""Constants for the entity_rename_safe integration."""

DOMAIN = "entity_rename_safe"
WORK_DIR_NAME = ".entity_rename_safe"
CONF_EXTERNAL_PATHS = "external_paths"

MAX_EXTERNAL_FILE_BYTES = 2 * 1024 * 1024
MAX_EXTERNAL_HITS = 500
EXTERNAL_SKIP_DIRS: tuple[str, ...] = (".git", "node_modules", "__pycache__", ".venv", "venv")

DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".storage",
    ".git",
    "custom_components",
    "deps",
    ".cloud",
    WORK_DIR_NAME,
    "secrets.yaml",
)
