import json
from pathlib import Path

from agents.orchestrator_agent import OrchestratorAgent
from llm.router import LLMRouter
from smartx.extraction import extract_document
from smartx.pipeline import SmartXPipeline
from smartx.schema import validate_document
from rag.retriever import SessionRetriever
from ui.streamlit_app import _download_csv, _download_excel, _download_json, _download_report, process_sources


def test_text_ingestion_provenance_and_schema():
    source = b"REQ-1: The system shall display status.\nThe system must log events."
    document = SmartXPipeline("do178c").ingest("requirements.txt", source)
    assert len(document.items) == 2
    assert document.provenance[0]["source_hash"]
    assert document.provenance[0]["source_hash"] == __import__("hashlib").sha256(source).hexdigest()
    assert document.provenance[0]["extraction_method"] == "text-lines"
    assert document.items[0]["provenance"]["line_start"] == 1
    assert document.metadata["processing_status"]["document_understanding"]["agent"] == "document_understanding"
    assert validate_document(document.to_dict()) == []


def test_supported_structured_formats():
    text, metadata, provenance = extract_document("data.json", b'{"requirement": "shall work"}')
    assert "shall work" in text and metadata["format"] == "json"
    text, metadata, _ = extract_document("data.xml", b"<root><item>shall work</item></root>")
    assert text == "shall work" and metadata["root"] == "root"


def test_orchestrator_returns_all_agents_and_fallback():
    document = SmartXPipeline().ingest("req.md", b"The system shall calculate a result.")
    result = OrchestratorAgent({"rules": ["review evidence"]}).run(document)
    assert {entry["agent"] for entry in result["results"]} == {"validation", "compliance", "traceability", "generation", "assistant"}
    assert "Deterministic" in LLMRouter().complete("hello")


def test_pasted_text_and_multiple_sources_without_api_keys():
    retriever = SessionRetriever()
    results = process_sources(
        "generic",
        "deterministic",
        [("pasted_text.txt", b"The system shall accept pasted text."), ("second.md", b"The system must log events.")],
        retriever,
    )
    assert len(results) == 2
    assert all(item["document"]["items"] for item in results)
    assert retriever.retrieve("pasted text")


def test_exports_are_available_without_external_api_keys():
    result = SmartXPipeline().run(SmartXPipeline().ingest("req.txt", b"The system shall work."))
    assert "agent,status" in _download_csv({"results": []})
    assert _download_excel(result)
    assert '"document"' in _download_json(result)
    report = _download_report(result)
    assert "SmartX review report" in report and "Human review required" in report
