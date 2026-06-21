"""MnM client integration layer (MacroQuest-style struct catalog + signatures)."""

from client_re.mnmlib.types import (
    MNMLIB_DIR,
    combat_type_keywords,
    generate_types_catalog,
    load_types_catalog,
    types_catalog_path,
)

__all__ = [
    "MNMLIB_DIR",
    "combat_type_keywords",
    "generate_types_catalog",
    "load_types_catalog",
    "types_catalog_path",
]
