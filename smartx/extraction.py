"""Multi-format extraction with optional readers and safe degradation."""

import csv
import hashlib
import io
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Tuple

from .models import Provenance


def _provenance(path: Path, extractor: str, source: bytes, text: str, confidence: float = 0.95) -> Dict[str, Any]:
    """Build stable source provenance; hashes always identify the original bytes."""
    return Provenance(
        path.name,
        path.suffix.lstrip(".") or "text",
        hashlib.sha256(source).hexdigest(),
        extraction_method=extractor,
        confidence=confidence if text else 0.35,
        extractor=extractor,
    ).__dict__


def _artifact_type(name: str, text: str, metadata: Dict[str, Any]) -> str:
    """Classify content using format and content signals, never extension alone."""
    lower = text.lower()
    if re.search(r"\b(?:void|int|bool|float|class|struct)\s+\w+\s*\(", text):
        return "code"
    if re.search(r"\b(test|verify|verification|assert|expected result)\b", lower):
        return "test"
    if re.search(r"^\s*#{1,6}\s+", text, re.MULTILINE) or "guidance" in lower:
        return "guidance"
    if re.search(r"\b(shall|must|should|required to)\b", lower):
        return "requirement"
    if re.search(r"\b(design|architecture|interface|component)\b", lower):
        return "design"
    return "unknown"


def extract_document(file_name: str, data: bytes) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Return text, structured metadata, and provenance for a supported upload."""
    path = Path(file_name)
    suffix = path.suffix.lower()
    warnings: list[str] = []
    if suffix in {".txt", ".md", ".c", ".h", ".cpp", ".cc", ".hpp"}:
        text = data.decode("utf-8", errors="replace")
        extractor = "text"
        metadata: Dict[str, Any] = {"format": suffix[1:] or "txt"}
    elif suffix == ".json":
        obj = json.loads(data.decode("utf-8"))
        text = json.dumps(obj, indent=2, ensure_ascii=False)
        metadata = {"format": "json", "structured": obj if isinstance(obj, (dict, list)) else {"value": obj}}
        extractor = "json"
    elif suffix == ".xml":
        root = ET.fromstring(data)
        text = "\n".join(part.strip() for part in root.itertext() if part.strip())
        metadata = {"format": "xml", "root": root.tag}
        extractor = "xml"
    elif suffix == ".csv":
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace"))))
        text = "\n".join("; ".join(f"{k}: {v}" for k, v in row.items()) for row in rows)
        metadata = {"format": "csv", "rows": rows, "columns": list(rows[0]) if rows else []}
        extractor = "csv"
    elif suffix in {".xlsx", ".xls"}:
        try:
            import pandas as pd  # type: ignore
            frame = pd.read_excel(io.BytesIO(data))
            rows = frame.fillna("").to_dict(orient="records")
            text = frame.to_csv(index=False)
            metadata = {"format": suffix[1:], "rows": rows, "columns": list(frame.columns)}
            extractor = "pandas"
        except Exception as exc:
            text = ""
            metadata = {"format": suffix[1:]}
            warnings.append(f"Excel extraction unavailable: {exc}")
            extractor = "unavailable"
    elif suffix == ".docx":
        try:
            from docx import Document  # type: ignore
            doc = Document(io.BytesIO(data))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            metadata = {"format": "docx", "paragraphs": len(doc.paragraphs), "locations": [{"paragraph": index + 1} for index, paragraph in enumerate(doc.paragraphs) if paragraph.text.strip()]}
            extractor = "python-docx"
        except Exception as exc:
            text, metadata, extractor = "", {"format": "docx"}, "unavailable"
            warnings.append(f"DOCX extraction unavailable: {exc}")
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
            reader = PdfReader(io.BytesIO(data))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n".join(pages)
            metadata = {"format": "pdf", "pages": len(pages), "locations": [{"page": index + 1} for index, page_text in enumerate(pages) if page_text.strip()]}
            extractor = "pypdf"
        except Exception as exc:
            text, metadata, extractor = "", {"format": "pdf"}, "unavailable"
            warnings.append(f"PDF extraction unavailable: {exc}")
    else:
        text = data.decode("utf-8", errors="replace")
        metadata = {"format": suffix[1:] if suffix else "unknown", "unknown_format": True}
        extractor = "text-unknown-format"
    metadata["artifact_type"] = _artifact_type(path.name, text, metadata)
    metadata["mixed_artifact_types"] = sorted({
        _artifact_type(path.name, line, metadata) for line in text.splitlines() if line.strip()
    } - {"unknown"})
    provenance = _provenance(path, extractor, data, text)
    if suffix in {".txt", ".md", ".c", ".h", ".cpp", ".cc", ".hpp"}:
        provenance["locations"] = [{"line_start": line, "line_end": line} for line, value in enumerate(text.splitlines(), 1) if value.strip()]
        provenance["extraction_method"] = "text-lines"
    elif suffix == ".csv":
        provenance["locations"] = [{"line_start": line, "line_end": line} for line in range(2, len(rows) + 2)]
    elif suffix in {".xlsx", ".xls"} and metadata.get("rows"):
        provenance["locations"] = [{"sheet": "Sheet1", "row": index + 2} for index in range(len(metadata["rows"]))]
    elif metadata.get("locations"):
        provenance["locations"] = metadata["locations"]
    if warnings:
        provenance["warnings"] = warnings
    return text, metadata, provenance


def split_requirements(text: str, metadata: Dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Normalize requirement-like rows while ignoring headings and decoration."""
    metadata = metadata or {}
    items: list[dict[str, Any]] = []
    structured = metadata.get("structured")
    if isinstance(structured, dict):
        candidates: list[str] = []
        for value in structured.values():
            if isinstance(value, str):
                candidates.append(value)
            elif isinstance(value, list):
                candidates.extend(str(item) for item in value if isinstance(item, (str, int, float)))
        for value in candidates:
            if re.search(r"\b(shall|must|should|required to)\b", value, re.I):
                items.append({"id": f"REQ-{len(items) + 1:04d}", "text": value.strip(), "type": "requirement", "provenance": {"extraction_method": "structured-normalization", "confidence": 0.95}})
        if items:
            return items
    aliases = {"requirement", "requirement_id", "req_id", "id", "text", "description", "shall"}
    rows = metadata.get("rows") if isinstance(metadata.get("rows"), list) else None
    if rows:
        for number, row in enumerate(rows, 2):
            if not isinstance(row, dict):
                continue
            keys = {str(key).strip().lower().replace(" ", "_"): value for key, value in row.items()}
            text_key = next((key for key in keys if key in aliases and key not in {"id", "requirement_id", "req_id"}), None)
            value = str(keys.get(text_key, "")).strip() if text_key else ""
            if not value:
                value = next((str(value).strip() for value in keys.values() if re.search(r"\b(shall|must|should)\b", str(value), re.I)), "")
            if not value:
                continue
            identifier = next((str(keys[key]).strip() for key in ("requirement_id", "req_id", "id") if keys.get(key)), f"REQ-{len(items) + 1:04d}")
            items.append({"id": identifier, "text": value, "source_line": number, "type": "requirement", "provenance": {"line_start": number, "line_end": number, "extraction_method": "tabular-normalization", "confidence": 0.95}})
        if items:
            return items
    for number, raw in enumerate(re.split(r"\n+", text), 1):
        value = re.sub(r"^\s*(?:[-*•]|\d+[.)]|>{1,})\s*", "", raw).strip()
        value = re.sub(r"^[=*_\-]{3,}$", "", value).strip()
        if not value or re.match(r"^#{1,6}\s+", value) or re.fullmatch(r"[|+\-: ]+", value):
            continue
        match = re.match(r"^(?P<id>[A-Za-z][\w.-]{1,30})\s*[:\-]\s*(?P<text>.+)$", value)
        identifier = match.group("id") if match else f"REQ-{len(items) + 1:04d}"
        candidate = match.group("text").strip() if match else value
        if not re.search(r"\b(shall|must|should|required to|requirement)\b", candidate, re.I):
            continue
        items.append({"id": identifier, "text": candidate, "source_line": number, "type": "requirement", "provenance": {"line_start": number, "line_end": number, "extraction_method": "text-lines", "confidence": 0.95}})
    return items