"""Small in-memory vector/lexical store for a Streamlit session."""

from dataclasses import dataclass
from typing import Any

from .embeddings import similarity


@dataclass
class Record:
	text: str
	metadata: dict[str, Any]


class VectorStore:
	def __init__(self): self.records: list[Record] = []

	def add(self, text: str, metadata: dict[str, Any] | None = None) -> None:
		if not isinstance(text, str) or not text.strip():
			return
		self.records.append(Record(text, metadata or {}))

	def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
		ranked = sorted(((similarity(query, r.text), r) for r in self.records), key=lambda pair: pair[0], reverse=True)
		return [{"score": score, "text": record.text, "metadata": record.metadata} for score, record in ranked[:limit] if score > 0]
