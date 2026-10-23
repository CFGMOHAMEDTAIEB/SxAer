"""Local validation datasets, workflow evaluation, metrics, and report exports."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from smartx.pipeline import SmartXPipeline


def _norm(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _set_match(expected: list[Any], actual: list[Any]) -> tuple[int, int, int]:
    expected_set, actual_set = {_norm(item) for item in expected}, {_norm(item) for item in actual}
    tp = len(expected_set & actual_set)
    return tp, len(expected_set - actual_set), len(actual_set - expected_set)


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip().lower())


def compare_values(expected: Any, actual: Any, mode: str = "exact", required_fields: tuple[str, ...] = ()) -> tuple[int, int, int]:
    """Compare semantic content independently from technical metadata."""
    mode = mode.replace("_", "-").lower()
    if mode == "exact":
        return _set_match(expected if isinstance(expected, list) else [expected], actual if isinstance(actual, list) else [actual])
    if mode == "required-fields":
        expected_rows = expected if isinstance(expected, list) else [expected]
        actual_rows = actual if isinstance(actual, list) else [actual]
        expected_keys = required_fields or tuple({key for row in expected_rows if isinstance(row, dict) for key in row})
        tp = sum(1 for row in actual_rows if isinstance(row, dict) and all(row.get(key) not in (None, "") for key in expected_keys))
        return min(tp, len(expected_rows)), max(0, len(expected_rows) - tp), max(0, len(actual_rows) - tp)
    if mode == "normalized":
        norm = lambda row: _normalized_text(row.get("text", row) if isinstance(row, dict) else row)
        expected_set, actual_set = {norm(row) for row in (expected if isinstance(expected, list) else [expected])}, {norm(row) for row in (actual if isinstance(actual, list) else [actual])}
        return len(expected_set & actual_set), len(expected_set - actual_set), len(actual_set - expected_set)
    if mode == "semantic":
        norm = lambda row: set(re.findall(r"[a-z0-9]+", _normalized_text(row.get("text", row) if isinstance(row, dict) else row)))
        expected_rows, actual_rows = expected if isinstance(expected, list) else [expected], actual if isinstance(actual, list) else [actual]
        matched = sum(1 for row in expected_rows if any(len(norm(row) & norm(candidate)) / max(1, len(norm(row) | norm(candidate))) >= 0.6 for candidate in actual_rows))
        return matched, len(expected_rows) - matched, max(0, len(actual_rows) - matched)
    raise ValueError(f"unsupported comparison mode: {mode}")


def validate_citations(expected: list[Any], actual: list[dict[str, Any]]) -> dict[str, Any]:
    """Match citations by chunk, source, location, and minimum score."""
    matched = 0
    for wanted in expected:
        wanted = wanted if isinstance(wanted, dict) else {"source": wanted}
        wanted_meta = wanted.get("metadata", {}) or {}
        for candidate in actual:
            candidate_meta = candidate.get("metadata", {}) or {}
            if wanted.get("chunk_id") and wanted["chunk_id"] != candidate.get("chunk_id"):
                continue
            wanted_source = wanted.get("source", wanted_meta.get("filename"))
            candidate_source = candidate.get("source", candidate_meta.get("filename", candidate_meta.get("source_name")))
            if wanted_source and wanted_source not in {candidate_source, candidate_meta.get("filename")}:
                continue
            location = wanted.get("location", wanted_meta.get("location"))
            if isinstance(location, dict) and any(candidate_meta.get(key) != value for key, value in location.items()):
                continue
            if wanted.get("score") is not None and float(candidate.get("score", candidate_meta.get("score", 0.0))) < float(wanted["score"]):
                continue
            matched += 1
            break
    return {"matched": matched, "expected": len(expected), "correctness": matched / len(expected) if expected else (1.0 if actual else 0.0)}


def _pr(tp: int, fn: int, fp: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}


@dataclass
class ValidationCase:
    name: str
    filename: str
    data: bytes = b""
    expected_document: dict[str, Any] = field(default_factory=dict)
    expected_findings: list[dict[str, Any]] = field(default_factory=list)
    expected_traceability: list[dict[str, Any]] = field(default_factory=list)
    profile: str = "generic"
    project: str = "validation"
    expected_citations: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["data"] = self.data.hex()
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ValidationCase":
        result = dict(value)
        result["data"] = bytes.fromhex(result.get("data", ""))
        return cls(**result)


@dataclass
class ValidationDataset:
    name: str
    cases: list[ValidationCase] = field(default_factory=list)
    version: str = "1"
    description: str = ""

    def add_case(self, case: ValidationCase) -> None:
        self.cases = [item for item in self.cases if item.name != case.name]
        self.cases.append(case)

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self) | {"cases": [case.to_dict() for case in self.cases]}, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ValidationDataset":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(raw["name"], [ValidationCase.from_dict(item) for item in raw.get("cases", [])], raw.get("version", "1"), raw.get("description", ""))


class ValidationEvaluator:
    def __init__(self, pipeline_factory=SmartXPipeline, comparison_mode: str = "normalized"):
        self.pipeline_factory, self.comparison_mode = pipeline_factory, comparison_mode

    def evaluate_case(self, case: ValidationCase) -> dict[str, Any]:
        started = time.perf_counter()
        retriever = None
        try:
            from rag.retriever import SessionRetriever
            retriever = SessionRetriever(persist_directory=tempfile.mkdtemp(prefix="smartx-eval-"), project=case.project, profile=case.profile)
            retriever.ingest_file(case.filename, case.data)
        except Exception:
            retriever = None
        try:
            pipeline = self.pipeline_factory(case.profile, retriever=retriever)
        except TypeError:
            pipeline = self.pipeline_factory(case.profile)
        document = pipeline.ingest(case.filename, case.data)
        result = pipeline.run(document)
        duration = time.perf_counter() - started
        actual_items = document.items
        expected_items = case.expected_document.get("items", [])
        mode = str(case.metadata.get("comparison_mode", self.comparison_mode))
        item_metrics = _pr(*compare_values(expected_items, actual_items, mode))
        actual_findings = [finding for agent in result.get("results", []) for finding in agent.get("findings", [])]
        finding_metrics = _pr(*compare_values(case.expected_findings, actual_findings, mode))
        actual_links = result.get("traceability", []) or next((agent.get("artifacts", {}).get("traceability_matrix", []) for agent in result.get("results", []) if agent.get("agent") == "traceability"), [])
        trace_metrics = _pr(*compare_values(case.expected_traceability, actual_links, mode))
        citations = result.get("citations", []) or [citation for agent in result.get("results", []) for citation in agent.get("artifacts", {}).get("citations", [])]
        citation_result = validate_citations(case.expected_citations, citations)
        citation_correctness = citation_result["correctness"]
        citation_false_positives = max(0, len(citations) - citation_result["matched"]) if case.expected_citations else 0
        classification = document.document_type == case.expected_document.get("document_type", document.document_type)
        review_rate = 1.0 if document.human_review_required else 0.0
        fallback_rate = 1.0 if any("fallback" in _norm(agent).lower() for agent in result.get("results", [])) else 0.0
        finding_tp, finding_fn, finding_fp = compare_values(case.expected_findings, actual_findings, mode)
        weakness = ["low extraction confidence"] if document.confidence < 0.75 else []
        if finding_fn: weakness.append(f"validation false negatives: {finding_fn}")
        if finding_fp: weakness.append(f"validation false positives: {finding_fp}")
        if citation_false_positives: weakness.append(f"citation false positives: {citation_false_positives}")
        return {"case": case.name, "filename": case.filename, "duration_seconds": duration, "metrics": {"extraction": item_metrics, "artifact_classification_accuracy": float(classification), "validation": {"false_positive_rate": finding_fp / max(1, finding_tp + finding_fp), "false_negative_rate": finding_fn / max(1, finding_tp + finding_fn), "true_positive": finding_tp, "false_positive": finding_fp, "false_negative": finding_fn}, "traceability": trace_metrics | {"coverage": trace_metrics["recall"]}, "rag_citation_correctness": citation_correctness, "citation_false_positive_count": citation_false_positives, "human_correction_rate": review_rate, "llm_fallback_rate": fallback_rate, "comparison_mode": mode}, "document": document.to_dict(), "result": result, "weaknesses": weakness}

    def evaluate(self, dataset: ValidationDataset) -> dict[str, Any]:
        cases = [self.evaluate_case(case) for case in dataset.cases]
        avg = sum(item["duration_seconds"] for item in cases) / len(cases) if cases else 0.0
        def average(path: tuple[str, ...], default=0.0):
            values = []
            for item in cases:
                value: Any = item["metrics"]
                for key in path:
                    value = value.get(key, default) if isinstance(value, dict) else default
                values.append(float(value))
            return sum(values) / len(values) if values else default
        metrics = {"extraction_precision": average(("extraction", "precision")), "extraction_recall": average(("extraction", "recall")), "classification_accuracy": average(("artifact_classification_accuracy",)), "validation_false_positive_rate": average(("validation", "false_positive_rate")), "validation_false_negative_rate": average(("validation", "false_negative_rate")), "traceability_precision": average(("traceability", "precision")), "traceability_recall": average(("traceability", "recall")), "traceability_coverage": average(("traceability", "coverage")), "rag_citation_correctness": average(("rag_citation_correctness",)), "human_correction_rate": average(("human_correction_rate",)), "llm_fallback_rate": average(("llm_fallback_rate",))}
        return {"dataset": dataset.name, "version": dataset.version, "case_count": len(cases), "average_processing_seconds": avg, "metrics": metrics, "before_after_compatible": {"legacy_metrics": metrics.copy(), "comparison_mode": self.comparison_mode}, "cases": cases, "weaknesses": sorted({weakness for case in cases for weakness in case["weaknesses"]})}

    @staticmethod
    def report_json(report: dict[str, Any]) -> str:
        return json.dumps(report, indent=2, ensure_ascii=False, default=str)

    @staticmethod
    def report_excel(report: dict[str, Any]) -> bytes:
        try:
            from io import BytesIO
            import pandas as pd
            target = BytesIO()
            pd.DataFrame([report.get("metrics", {})]).to_excel(target, index=False)
            return target.getvalue()
        except Exception:
            return ValidationEvaluator.report_json(report).encode("utf-8")

    @staticmethod
    def report_pdf(report: dict[str, Any]) -> bytes | None:
        try:
            from io import BytesIO
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen.canvas import Canvas
            target = BytesIO(); page = Canvas(target, pagesize=letter)
            page.drawString(40, 750, f"SmartX validation: {report.get('dataset', 'dataset')}")
            page.drawString(40, 730, f"Cases: {report.get('case_count', 0)}")
            page.drawString(40, 710, f"Extraction recall: {report.get('metrics', {}).get('extraction_recall', 0):.2%}")
            page.save(); return target.getvalue()
        except Exception:
            return None


def build_regression_dataset() -> ValidationDataset:
    cases = [
        ("txt", "requirements.txt", b"The system shall record events."),
        ("xml", "requirements.xml", b"<requirements><requirement>The system shall record events.</requirement></requirements>"),
        ("c", "controller.c", b"void record_event(void) { /* requirement */ }"),
        ("markdown", "guidance.md", b"# Guidance\nThe system shall be testable."),
        ("json", "requirements.json", b'{"requirement": "The system shall record events."}'),
    ]
    try:
        from docx import Document
        from io import BytesIO
        buffer = BytesIO(); document = Document(); document.add_paragraph("The system shall record events."); document.save(buffer)
        cases.append(("docx", "requirements.docx", buffer.getvalue()))
    except Exception:
        pass
    try:
        from io import BytesIO
        import pandas as pd
        buffer = BytesIO(); pd.DataFrame({"requirement": ["The system shall record events."]}).to_excel(buffer, index=False)
        cases.append(("excel", "requirements.xlsx", buffer.getvalue()))
    except Exception:
        pass
    try:
        from io import BytesIO
        from reportlab.pdfgen.canvas import Canvas
        buffer = BytesIO(); page = Canvas(buffer); page.drawString(40, 750, "The system shall record events."); page.save()
        cases.append(("pdf", "requirements.pdf", buffer.getvalue()))
    except Exception:
        pass
    golden_cases = []
    for name, filename, data in cases:
        is_code = name == "c"
        expected = {"document_type": "code" if is_code else ("guidance" if name == "markdown" else "requirement")}
        if not is_code:
            expected_text = "The system shall be testable." if name == "markdown" else "The system shall record events."
            expected["items"] = [{"id": "REQ-0001", "text": expected_text}]
        golden_cases.append(ValidationCase(name, filename, data, expected_document=expected, expected_citations=[filename]))
    return ValidationDataset("smartx-regression", golden_cases, description="Built-in non-proprietary regression samples; expected fields are reviewer-approved golden content.")
