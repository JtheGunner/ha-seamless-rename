"""Constants for the entity_rename_safe integration."""

DOMAIN = "entity_rename_safe"
WORK_DIR_NAME = ".entity_rename_safe"

DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".storage",
    ".git",
    "custom_components",
    "deps",
    ".cloud",
    WORK_DIR_NAME,
    "secrets.yaml",
)
