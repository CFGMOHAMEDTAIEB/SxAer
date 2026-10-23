"""Persistent, profile-isolated knowledge storage with a dependency-free fallback."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .embeddings import similarity


def _safe(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "_", value.lower()).strip("_") or "generic"


class KnowledgeBase:
    """Store chunks in Chroma when available, otherwise in JSON files.

    The fallback is intentionally local and clearly marked; it preserves the same
    API so tests and offline deployments remain useful without embedding models.
    """

    def __init__(
        self,
        persist_dir: str | Path | None = None,
        project: str = "default",
        profile: str = "generic",
        *,
        persist_directory: str | Path | None = None,
    ):
        if persist_dir is not None and persist_directory is not None and Path(persist_dir) != Path(persist_directory):
            raise ValueError("persist_dir and persist_directory must refer to the same directory")
        storage_dir = persist_directory if persist_directory is not None else persist_dir
        self.persist_dir = Path(storage_dir or os.getenv("SMARTX_CHROMA_DIR", ".smartx_chroma"))
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.project, self.profile = project, profile
        self.collection_name = f"smartx_{_safe(project)}_{_safe(profile)}"
        self.backend = "fallback"
        self._chroma = None
        try:
            import chromadb  # type: ignore
            self._chroma = chromadb.PersistentClient(path=str(self.persist_dir))
            self.collection = self._chroma.get_or_create_collection(self.collection_name, metadata={"project": project, "profile": profile, "hnsw:space": "cosine"})
            self.backend = "chroma"
        except Exception:
            self.collection = None
        self._fallback_path = self.persist_dir / f"{self.collection_name}.json"
        self._records: list[dict[str, Any]] = self._load_fallback()

    def _scope_where(self, **extra: Any) -> dict[str, Any]:
        clauses = [{"project": self.project}, {"profile": self.profile}]
        clauses.extend({key: value} for key, value in extra.items())
        return {"$and": clauses}

    def _scope_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            record
            for record in records
            if record.get("metadata", {}).get("project") == self.project
            and record.get("metadata", {}).get("profile") == self.profile
        ]

    def _load_chroma_records(self) -> list[dict[str, Any]]:
        if self.backend != "chroma" or self.collection is None:
            return []
        try:
            result = self.collection.get(where=self._scope_where(), include=["documents", "metadatas"])
            ids = result.get("ids", [])
            documents = result.get("documents", []) or []
            metadatas = result.get("metadatas", []) or []
            return [
                {"id": chunk_id, "text": documents[index], "metadata": metadatas[index] or {}}
                for index, chunk_id in enumerate(ids)
                if index < len(documents)
            ]
        except Exception:
            return []

    def _records_for_views(self) -> list[dict[str, Any]]:
        chroma_records = self._load_chroma_records()
        if chroma_records:
            return chroma_records
        return self._scope_records(self._records)

    def _load_fallback(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self._fallback_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_fallback(self) -> None:
        self._fallback_path.write_text(json.dumps(self._records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def _hash_exists(self, source_hash: str) -> bool:
        if not source_hash:
            return False
        if self.backend == "chroma":
            try:
                return bool(self.collection.get(where=self._scope_where(source_hash=source_hash), limit=1)["ids"])
            except Exception:
                pass
        return any(
            r.get("metadata", {}).get("source_hash") == source_hash
            for r in self._scope_records(self._records)
        )

    def add_document(self, filename: str, data: bytes, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        source_hash = hashlib.sha256(data).hexdigest()
        if self._hash_exists(source_hash):
            return {"status": "duplicate", "source_hash": source_hash, "filename": filename, "chunks": 0}
        chunks = chunk_text(text)
        base = {**(metadata or {}), "filename": filename, "source_hash": source_hash, "project": self.project, "profile": self.profile}
        base = {key: value for key, value in base.items() if isinstance(value, (str, int, float, bool)) and value is not None}
        records = []
        for index, chunk in enumerate(chunks):
            chunk_id = f"{source_hash[:16]}-{index:04d}"
            item_metadata = {**base, **chunk["location"], "chunk_index": index, "extraction_method": base.get("extraction_method", "unknown"), "confidence": float(base.get("confidence", 0.0))}
            records.append({"id": chunk_id, "text": chunk["text"], "metadata": item_metadata})
        if self.backend == "chroma" and records:
            try:
                self.collection.add(ids=[r["id"] for r in records], documents=[r["text"] for r in records], metadatas=[r["metadata"] for r in records])
            except Exception:
                self.backend = "fallback"
        self._records.extend(records)
        self._save_fallback()
        return {"status": "indexed", "source_hash": source_hash, "filename": filename, "chunks": len(records), "collection": self.collection_name}

    def add_knowledge(self, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        encoded = text.encode("utf-8")
        return self.add_document(metadata.get("filename", "knowledge.txt") if metadata else "knowledge.txt", encoded, text, metadata)

    def retrieve(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if self.backend == "chroma":
            try:
                result = self.collection.query(query_texts=[query], n_results=limit, where=self._scope_where())
                return [{"chunk_id": ids[0], "text": docs[0], "score": max(0.0, 1.0 - float(distances[0])), "metadata": metas[0]} for ids, docs, distances, metas in zip(result.get("ids", [[]]), result.get("documents", [[]]), result.get("distances", [[]]), result.get("metadatas", [[]]))]
            except Exception:
                pass
        ranked = sorted(((similarity(query, r["text"]), r) for r in self._scope_records(self._records)), key=lambda pair: pair[0], reverse=True)
        return [{"chunk_id": record["id"], "text": record["text"], "score": score, "metadata": record["metadata"]} for score, record in ranked[:limit] if score > 0]

    def list_documents(self) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for record in self._records_for_views():
            meta = record["metadata"]
            item = grouped.setdefault(meta.get("source_hash", record["id"]), {k: meta.get(k) for k in ("filename", "source_hash", "project", "profile")})
            item["chunks"] = item.get("chunks", 0) + 1
        return list(grouped.values())

    def list_collections(self) -> list[str]:
        names = {path.stem for path in self.persist_dir.glob("smartx_*.json")}
        if self.backend == "chroma":
            try:
                names.update(item.name for item in self._chroma.list_collections())
            except Exception:
                pass
        return sorted(names)

    def preview(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._records_for_views()[:limit]

    def clear(self) -> None:
        if self.backend == "chroma":
            try:
                self._chroma.delete_collection(self.collection_name)
                self.collection = self._chroma.get_or_create_collection(self.collection_name, metadata={"project": self.project, "profile": self.profile})
            except Exception:
                pass
        self._records = []
        self._save_fallback()

    def rebuild(self) -> None:
        self.clear()


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 120) -> list[dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines and text.strip():
        lines = [text.strip()]
    chunks, current, start = [], [], 1
    size = 0
    for line_no, line in enumerate(lines, 1):
        if current and size + len(line) + 1 > max_chars:
            chunks.append({"text": "\n".join(current), "location": {"line_start": start, "line_end": line_no - 1}})
            tail = current[-1:] if overlap else []
            current, size, start = tail, sum(map(len, tail)), line_no
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append({"text": "\n".join(current), "location": {"line_start": start, "line_end": len(lines)}})
    return chunks