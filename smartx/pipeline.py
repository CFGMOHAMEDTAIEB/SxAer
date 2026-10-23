"""End-to-end SmartX orchestration."""

from pathlib import Path
from typing import Any, Dict

from .extraction import extract_document, split_requirements
from .models import SmartXDocument
from .profiles import get_profile
from .schema import validate_document, validate_items


class SmartXPipeline:
    def __init__(self, profile: str = "generic", llm_router: Any = None, retriever: Any = None) -> None:
        self.profile_name, self.profile, self.llm_router, self.retriever = profile, get_profile(profile), llm_router, retriever

    def ingest(self, file_name: str, data: bytes) -> SmartXDocument:
        from agents.document_understanding_agent import DocumentUnderstandingAgent

        understanding = DocumentUnderstandingAgent().run(file_name, data)
        text = understanding.artifacts["content"]
        metadata = understanding.artifacts["metadata"]
        provenance = understanding.artifacts["provenance"]
        items = understanding.artifacts["items"]
        warnings = list(provenance.get("warnings", [])) + validate_items(items)
        confidence = understanding.confidence
        metadata = {**metadata, "profile_config": self.profile, "processing_status": {"document_understanding": understanding.to_dict()}}
        document_type = str(metadata.get("artifact_type") or "unknown")
        document = SmartXDocument(document_type=document_type, title=Path(file_name).stem, content=text, items=items, metadata=metadata, provenance=[provenance], profile=self.profile_name, confidence=confidence, human_review_required=understanding.human_review_required or bool(warnings), warnings=warnings)
        errors = validate_document(document.to_dict())
        document.warnings.extend(errors)
        document.human_review_required |= bool(errors)
        return document

    def run(self, document: SmartXDocument) -> Dict[str, Any]:
        from agents.orchestrator_agent import OrchestratorAgent
        result = OrchestratorAgent(self.profile, self.llm_router, self.retriever).run(document)
        result["processing_status"] = document.metadata.get("processing_status", {})
        return result

    def run_milestone3(self, user_request: str, file_name: str, data: bytes, *, storage_dir: str = ".smartx_jobs", limits=None):
        """Run the resumable Milestone 3 workflow without changing ``run``."""
        from core.milestone3 import SmartXWorkflow

        workflow = SmartXWorkflow(self.profile, self.llm_router, self.retriever, storage_dir=storage_dir, limits=limits)
        state = workflow.new_state(user_request, [(file_name, data)], profile=self.profile_name)
        return workflow.run(state)