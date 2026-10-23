"""Persistent profile-isolated retrieval over built-in and uploaded evidence."""

from smartx.extraction import extract_document
from smartx.profiles import load_profiles
from .knowledge_base import KnowledgeBase


class SessionRetriever:
	def __init__(self, persist_dir=None, project="default", profile="generic", *, persist_directory=None):
		self.project, self.profile = project, profile
		self.store = KnowledgeBase(persist_dir, project, profile, persist_directory=persist_directory)
		if not self.store.list_documents():
			for name, profile_data in load_profiles().items():
				if name == profile or name == "generic":
					self.add_knowledge(str(profile_data), {"filename": f"builtin-{name}.json", "source": "builtin-profile", "profile": name, "extraction_method": "profile-config", "confidence": 1.0})

	def add_document(self, name: str, text: str, provenance=None) -> None:
		metadata = {"filename": name, "source": name, **(provenance or {})}
		return self.store.add_document(name, text.encode("utf-8"), text, metadata)

	def ingest_file(self, name: str, data: bytes, project_rules: bool = False):
		text, metadata, provenance = extract_document(name, data)
		combined = {**metadata, **provenance, "source": "project-rule" if project_rules else "upload"}
		return self.store.add_document(name, data, text, combined)

	def add_knowledge(self, text: str, metadata=None) -> None:
		"""Index non-empty knowledge safely; malformed metadata cannot break a session."""
		try:
			return self.store.add_knowledge(text or "", metadata if isinstance(metadata, dict) else {})
		except (TypeError, ValueError):
			return {"status": "ignored", "chunks": 0}

	def retrieve(self, query: str, limit: int = 5):
		return self.store.retrieve(query, limit)

	def list_documents(self):
		return self.store.list_documents()

	def preview(self, limit=20):
		return self.store.preview(limit)

	def list_collections(self):
		return self.store.list_collections()

	def clear(self):
		self.store.clear()

	def rebuild(self):
		self.store.rebuild()


Retriever = SessionRetriever
