"""Project/customer-isolated learned mappings and golden examples."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LearnedCorrectionsStore:
    def __init__(self, directory: str | Path = ".smartx_learning", project: str = "default", customer: str | None = None):
        self.directory, self.project, self.customer = Path(directory), project, customer or project
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "corrections.json"

    def _read(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _scope(self, row: dict[str, Any]) -> bool:
        return row.get("project") == self.project and row.get("customer") == self.customer

    def add(self, kind: str, input_value: Any, correction: Any, *, golden: bool = False) -> dict[str, Any]:
        rows = self._read()
        row = {"id": f"LC-{len(rows) + 1:06d}", "project": self.project, "customer": self.customer, "kind": kind, "input": input_value, "correction": correction, "golden": golden, "enabled": True}
        rows.append(row)
        self.path.write_text(json.dumps(rows, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return row

    def list(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        return [row for row in self._read() if self._scope(row) and (include_disabled or row.get("enabled", True))]

    def reuse(self, kind: str, input_value: Any) -> list[dict[str, Any]]:
        return [row for row in self.list() if row.get("kind") == kind and row.get("input") == input_value]

    def disable(self, correction_id: str) -> bool:
        return self._set(correction_id, enabled=False)

    def delete(self, correction_id: str) -> bool:
        rows = self._read(); kept = [row for row in rows if not (self._scope(row) and row.get("id") == correction_id)]
        changed = len(kept) != len(rows)
        if changed: self.path.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
        return changed

    def _set(self, correction_id: str, **updates: Any) -> bool:
        rows = self._read(); changed = False
        for row in rows:
            if self._scope(row) and row.get("id") == correction_id:
                row.update(updates); changed = True
        if changed: self.path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        return changed