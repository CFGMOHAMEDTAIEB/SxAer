"""Configurable SmartX profiles backed by repository JSON files."""

import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs"

BUILTIN_PROFILES: Dict[str, Dict[str, Any]] = {
    "generic": {"name": "Generic", "rules": ["Every requirement must have an identifier and verifiable wording."]},
    "do178c": {"name": "DO-178C", "standard": "DO-178C", "rules": ["Requirements should be uniquely identified.", "Verification method and objective evidence should be stated."]},
    "gt44": {"name": "GT44", "customer": "GT44", "rules": ["Capture requirement source and assurance context."]},
    "airbus": {"name": "Airbus", "customer": "Airbus", "rules": ["Preserve customer and system-level traceability."]},
    "safran": {"name": "Safran", "customer": "Safran", "rules": ["Make compliance evidence and review ownership explicit."]},
}


def load_profiles() -> Dict[str, Dict[str, Any]]:
    profiles = dict(BUILTIN_PROFILES)
    for path in CONFIG_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            profiles[path.stem.lower()] = {**profiles.get(path.stem.lower(), {}), **data}
        except (OSError, json.JSONDecodeError):
            continue
    return profiles


def get_profile(name: str | None) -> Dict[str, Any]:
    profiles = load_profiles()
    key = (name or "generic").lower().replace("-", "")
    aliases = {"generic": "generic", "do178c": "do178c", "do178": "do178c", "gt44": "gt44"}
    return profiles.get(aliases.get(key, key), profiles["generic"])