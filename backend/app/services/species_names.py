"""Hebrew display names, loaded from data/species_he.json (edit that file to add translations).

Keys are lowercase English names as returned by SpeciesNet; unknown names fall back to English.
"""

import json
from pathlib import Path

HEBREW_FILE = Path(__file__).resolve().parent.parent / "data" / "species_he.json"


def _load() -> dict[str, str]:
    data = json.loads(HEBREW_FILE.read_text(encoding="utf-8"))
    return {k.strip().lower(): v for k, v in data.items()}


HEBREW = _load()


def display_name(species: str) -> str:
    return HEBREW.get(species.strip().lower(), species)
