"""SmartX schema validation without requiring jsonschema."""

from typing import Any, Dict, Iterable

REQUIRED_KEYS = ("document_type", "content", "items", "provenance", "profile", "confidence", "human_review_required")


def validate_document(document: Dict[str, Any]) -> list[str]:
    errors = [f"Missing required field: {key}" for key in REQUIRED_KEYS if key not in document]
    if "items" in document and not isinstance(document["items"], list): errors.append("items must be an array")
    if "confidence" in document and not isinstance(document["confidence"], (int, float)): errors.append("confidence must be numeric")
    return errors


def validate_items(items: Iterable[Dict[str, Any]]) -> list[str]:
    errors = []
    for index, item in enumerate(items):
        if not item.get("id"): errors.append(f"Item {index} has no id")
        if not item.get("text"): errors.append(f"Item {index} has no text")
    return errors