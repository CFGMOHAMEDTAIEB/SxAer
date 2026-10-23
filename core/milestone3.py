"""Typed, local-first Milestone 3 workflow services.

This module intentionally avoids a graph framework and external services.  The
state transitions are explicit and serialisable, which makes the workflow easy
to resume, audit, and test offline.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from agents.assistant_agent import AssistantAgent
from agents.compliance_agent import ComplianceAgent
from agents.document_understanding_agent import DocumentUnderstandingAgent
from agents.generation_agent import GenerationAgent
from agents.traceability_agent import TraceabilityAgent
from agents.validation_agent import ValidationAgent
from smartx.models import SmartXDocument


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _restore_json_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__bytes__"}:
        return bytes.fromhex(value["__bytes__"])
    if isinstance(value, dict):
        return {key: _restore_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_restore_json_value(item) for item in value]
    return value


def _plain(value: Any, active: set[int] | None = None) -> Any:
    """Convert state to JSON-safe data without recursing through accidental cycles."""
    active = active or set()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    identity = id(value)
    if identity in active:
        return "[cycle omitted]"
    active.add(identity)
    try:
        if is_dataclass(value):
            return {item.name: _plain(getattr(value, item.name), active) for item in fields(value)}
        if isinstance(value, dict):
            return {str(key): _plain(item, active) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_plain(item, active) for item in value]
        return str(value)
    finally:
        active.remove(identity)


class WorkflowState(str, Enum):
    QUEUED = "queued"
    DOCUMENT_UNDERSTANDING = "document_understanding"
    VALIDATION = "validation"
    COMPLIANCE = "compliance"
    TRACEABILITY = "traceability"
    GENERATION = "generation"
    ASSISTANT = "assistant"
    REPORTING = "reporting"
    WAITING_FOR_REVIEW = "waiting_for_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ReviewDecision = Literal["approve", "reject", "correct"]


@dataclass(frozen=True)
class RouteDecision:
    """Deterministic, explainable routing result for a workflow step."""

    target: str
    reason: str
    requires_review: bool = False


def route_request(*, current: str, confidence: float = 1.0, valid_json: bool = True,
                  evidence: bool = True, rule_conflict: bool = False,
                  approved: bool = False, request: str = "") -> RouteDecision:
    """Select the next node without depending on LangGraph or an LLM."""
    if not valid_json:
        return RouteDecision(current, "invalid_json_repair", True)
    if confidence < 0.5:
        return RouteDecision(WorkflowState.WAITING_FOR_REVIEW.value, "low_confidence", True)
    if rule_conflict:
        return RouteDecision(WorkflowState.WAITING_FOR_REVIEW.value, "rule_conflict", True)
    if not evidence:
        return RouteDecision(WorkflowState.WAITING_FOR_REVIEW.value, "insufficient_evidence", True)
    if current == WorkflowState.QUEUED.value:
        return RouteDecision(WorkflowState.DOCUMENT_UNDERSTANDING.value, "start_document_understanding")
    if current == WorkflowState.DOCUMENT_UNDERSTANDING.value:
        return RouteDecision(WorkflowState.VALIDATION.value, "document_understood")
    if current == WorkflowState.VALIDATION.value:
        target = WorkflowState.COMPLIANCE.value if "compliance" in request.lower() else WorkflowState.TRACEABILITY.value
        return RouteDecision(target, "requirement_path" if target == WorkflowState.COMPLIANCE.value else "requirement_traceability_path")
    if current == WorkflowState.COMPLIANCE.value:
        return RouteDecision(WorkflowState.TRACEABILITY.value, "compliance_checked")
    if current == WorkflowState.TRACEABILITY.value:
        return RouteDecision(WorkflowState.GENERATION.value, "traceability_checked")
    if current == WorkflowState.GENERATION.value:
        return RouteDecision(WorkflowState.ASSISTANT.value if not approved else WorkflowState.REPORTING.value, "approved_generation" if approved else "generation_review")
    if current == WorkflowState.ASSISTANT.value:
        return RouteDecision(WorkflowState.REPORTING.value, "assistant_complete")
    if current == WorkflowState.REPORTING.value:
        return RouteDecision(WorkflowState.COMPLETED.value, "report_complete")
    return RouteDecision(current, "awaiting_review", True)


@dataclass
class ReviewTask:
    id: str
    kind: str
    project: str
    source: str
    location: str = ""
    proposal: Any = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    status: str = "open"
    comments: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    decided_at: str | None = None
    reviewer: str | None = None
    decision: str | None = None
    correction: Any = None

    def decide(self, decision: str, reviewer: str, comment: str = "", correction: Any = None) -> None:
        if decision not in {"approve", "reject", "correct"}:
            raise ValueError("decision must be approve, reject, or correct")
        if self.status != "open":
            raise ValueError("review task is already decided")
        self.status, self.decision, self.reviewer = decision, decision, reviewer
        self.correction, self.decided_at = correction, _now()
        if comment:
            self.comments.append({"author": reviewer, "text": comment, "created_at": self.decided_at})


@dataclass
class TraceabilityLink:
    id: str
    source_id: str
    target_id: str
    link_type: str
    origin: str = "deterministic"
    confidence: float = 0.0
    evidence: list[dict[str, Any]] = field(default_factory=list)
    review_status: str = "not_required"
    reviewer_decision: str | None = None


@dataclass
class AuditEvent:
    event: str
    job_id: str
    project: str
    state: str
    timestamp: str = field(default_factory=_now)
    agent: str | None = None
    tool: str | None = None
    rule_version: str = "local-v1"
    prompt_version: str = "deterministic-v1"
    model_version: str = "deterministic"
    profile_version: str = "config-v1"
    input_hash: str = ""
    output_hash: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    human_decision: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentState:
    job_id: str
    user_request: str
    project: str = "default"
    customer: str = "default"
    role: str = "engineer"
    profile: str = "generic"
    input_artifact_ids: list[str] = field(default_factory=list)
    smartx_artifacts: dict[str, Any] = field(default_factory=dict)
    retrieved_knowledge: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    agent_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)
    generated_artifacts: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    review_tasks: list[ReviewTask] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    execution_history: list[AuditEvent] = field(default_factory=list)
    current_state: str = WorkflowState.QUEUED.value
    next_state: str | None = WorkflowState.DOCUMENT_UNDERSTANDING.value
    final_status: str = "queued"
    cancelled: bool = False
    steps: int = 0
    retry_count: int = 0
    tool_allowlist: list[str] = field(default_factory=list)
    sensitive_logging: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentState":
        values = dict(data)
        values["review_tasks"] = [ReviewTask(**item) for item in values.get("review_tasks", [])]
        values["execution_history"] = [AuditEvent(**item) for item in values.get("execution_history", [])]
        return cls(**values)


@dataclass
class WorkflowLimits:
    max_steps: int = 32
    timeout_seconds: float = 120.0
    max_input_bytes: int = 10 * 1024 * 1024
    max_tokens: int = 12000
    max_cost: float = 5.0


@dataclass
class JobRecord:
    job_id: str
    project: str
    status: str = WorkflowState.QUEUED.value
    progress: float = 0.0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    state: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    error: str | None = None


class _JsonStore:
    def __init__(self, directory: str | Path, filename: str, project: str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / filename
        self.project = project

    def _read(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write(self, rows: list[dict[str, Any]]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(_json_value(rows), indent=2, default=str), encoding="utf-8")
        temporary.replace(self.path)


class JobStore(_JsonStore):
    """Atomic JSON job persistence with project/customer isolation."""

    def __init__(self, directory: str | Path, project: str = "default"):
        super().__init__(directory, "jobs.json", project)

    def save(self, job: JobRecord) -> JobRecord:
        rows = [row for row in self._read() if row.get("job_id") != job.job_id or row.get("project") != self.project]
        job.project = self.project
        job.updated_at = _now()
        rows.append(asdict(job))
        self._write(rows)
        return job

    def create(self, state: AgentState) -> JobRecord:
        job = JobRecord(state.job_id, self.project, state=state.to_dict())
        return self.save(job)

    def get(self, job_id: str) -> JobRecord | None:
        for row in self._read():
            if row.get("job_id") == job_id and row.get("project") == self.project:
                row["state"] = _restore_json_value(row.get("state", {}))
                return JobRecord(**row)
        return None

    def recover_interrupted(self) -> list[JobRecord]:
        recovered = []
        for row in self._read():
            if row.get("project") == self.project and row.get("status") == "running":
                row["status"] = WorkflowState.QUEUED.value
                row["error"] = "recovered after interrupted execution"
                recovered.append(JobRecord(**row))
        if recovered:
            rows = self._read()
            for item in recovered:
                for row in rows:
                    if row.get("job_id") == item.job_id and row.get("project") == self.project:
                        row.update(asdict(item))
            self._write(rows)
        return recovered

    def cancel(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if not job:
            raise KeyError(job_id)
        job.status = WorkflowState.CANCELLED.value
        return self.save(job)

    def retry(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job.status not in {WorkflowState.FAILED.value, WorkflowState.CANCELLED.value}:
            raise ValueError("only failed or cancelled jobs can be retried")
        job.status, job.error = WorkflowState.QUEUED.value, None
        job.attempts += 1
        return self.save(job)


class ReviewStore(_JsonStore):
    def __init__(self, directory: str | Path, project: str = "default"):
        super().__init__(directory, "reviews.json", project)

    def save(self, task: ReviewTask) -> ReviewTask:
        rows = [row for row in self._read() if row.get("id") != task.id or row.get("project") != self.project]
        rows.append(asdict(task))
        self._write(rows)
        return task

    def list(self, status: str | None = None) -> list[ReviewTask]:
        return [ReviewTask(**row) for row in self._read() if row.get("project") == self.project and (status is None or row.get("status") == status)]

    def decide(self, task_id: str, decision: str, reviewer: str, comment: str = "", correction: Any = None) -> ReviewTask:
        task = next((item for item in self.list() if item.id == task_id), None)
        if task is None:
            raise KeyError(task_id)
        task.decide(decision, reviewer, comment, correction)
        return self.save(task)


class SmartXWorkflow:
    """Resumable state machine equivalent to a small orchestration graph."""

    AGENTS = {
        WorkflowState.VALIDATION.value: ValidationAgent,
        WorkflowState.COMPLIANCE.value: ComplianceAgent,
        WorkflowState.TRACEABILITY.value: TraceabilityAgent,
        WorkflowState.GENERATION.value: GenerationAgent,
        WorkflowState.ASSISTANT.value: AssistantAgent,
    }

    def __init__(self, profile: dict[str, Any] | None = None, llm_router: Any = None, retriever: Any = None, *, storage_dir: str | Path = ".smartx_jobs", limits: WorkflowLimits | None = None, project: str = "default"):
        self.profile = profile or {}
        self.llm_router, self.retriever = llm_router, retriever
        self.limits = limits or WorkflowLimits()
        self.project = project
        self.jobs, self.reviews = JobStore(storage_dir, project), ReviewStore(storage_dir, project)
        self.graph_backend = self._graph_backend()

    @staticmethod
    def _graph_backend() -> str:
        """Use LangGraph only when importable; the local engine remains the fallback."""
        try:
            import langgraph  # type: ignore  # optional dependency
            return "langgraph" if getattr(langgraph, "__version__", None) else "state_machine"
        except (ImportError, AttributeError):
            return "state_machine"

    def new_state(self, user_request: str, input_artifacts: Iterable[tuple[str, bytes]] = (), profile: str = "generic") -> AgentState:
        artifacts = list(input_artifacts)
        if any(len(data) > self.limits.max_input_bytes for _, data in artifacts):
            raise ValueError("input artifact exceeds configured size limit")
        state = AgentState(job_id=secrets.token_hex(8), user_request=user_request, project=self.project, customer=self.project, profile=profile)
        state.input_artifact_ids = [_hash({"name": name, "data": data.hex()}) for name, data in artifacts]
        state.smartx_artifacts["inputs"] = [{"name": name, "data": data} for name, data in artifacts]
        self.jobs.create(state)
        return state

    def _audit(self, state: AgentState, event: str, agent: str | None = None, before: Any = None, after: Any = None, citations: list[dict[str, Any]] | None = None, metadata: dict[str, Any] | None = None) -> None:
        safe_metadata = metadata or {}
        if state.sensitive_logging:
            safe_metadata = {key: value for key, value in safe_metadata.items() if "secret" not in key.lower() and "key" not in key.lower() and "token" not in key.lower()}
        state.execution_history.append(AuditEvent(event, state.job_id, state.project, state.current_state, agent=agent, tool=safe_metadata.pop("tool", None), input_hash=_hash(before) if before is not None else "", output_hash=_hash(after) if after is not None else "", citations=citations or [], metadata=safe_metadata))

    def _review(self, state: AgentState, kind: str, proposal: Any, citations: list[dict[str, Any]] | None = None, source: str = "workflow") -> None:
        task = ReviewTask(f"REV-{secrets.token_hex(6)}", kind, state.project, source, proposal=proposal, citations=citations or [])
        state.review_tasks.append(task)
        self.reviews.save(task)

    def _transition(self, state: AgentState, next_state: str) -> None:
        previous = state.current_state
        state.current_state, state.next_state = next_state, None
        self._audit(state, "state_transition", metadata={"from": previous, "to": next_state})

    def _run_understanding(self, state: AgentState) -> None:
        inputs = state.smartx_artifacts.get("inputs", [])
        if not inputs:
            raise ValueError("at least one input artifact is required")
        name, data = inputs[0]["name"], inputs[0]["data"]
        result = DocumentUnderstandingAgent().run(name, data.encode("utf-8") if isinstance(data, str) else data)
        state.smartx_artifacts["document"] = SmartXDocument(title=name, content=result.artifacts["content"], items=result.artifacts["items"], metadata=result.artifacts["metadata"], provenance=[result.artifacts["provenance"]], profile=state.profile, confidence=result.confidence, human_review_required=result.human_review_required, warnings=result.artifacts["provenance"].get("warnings", [])).to_dict()
        state.confidence = result.confidence
        state.warnings.extend(result.artifacts["provenance"].get("warnings", []))
        state.agent_results["document_understanding"] = result.to_dict()
        self._audit(state, "agent_completed", "document_understanding", inputs, result.to_dict(), state.citations, {"tool": "document_extractor"})
        if result.human_review_required:
            self._review(state, "low_confidence_translation", result.artifacts, source=name)
            state.current_state = WorkflowState.WAITING_FOR_REVIEW.value
            state.next_state = WorkflowState.VALIDATION.value
            self._audit(state, "state_transition", metadata={"from": WorkflowState.DOCUMENT_UNDERSTANDING.value, "to": WorkflowState.WAITING_FOR_REVIEW.value, "resume": state.next_state})
        else:
            self._transition(state, WorkflowState.VALIDATION.value)

    def _run_agent(self, state: AgentState) -> None:
        document = SmartXDocument(**{key: value for key, value in state.smartx_artifacts["document"].items() if key in SmartXDocument.__dataclass_fields__})
        agent_type = self.AGENTS[state.current_state]
        evidence = state.retrieved_knowledge
        result = agent_type(self.profile, self.llm_router, evidence).run(document)
        state.agent_results[state.current_state] = result.to_dict()
        state.findings.extend(result.findings)
        state.citations.extend(result.artifacts.get("citations", []))
        self._audit(state, "agent_completed", state.current_state, document.to_dict(), result.to_dict(), result.artifacts.get("citations", evidence), {"tool": state.current_state})
        if state.current_state == WorkflowState.TRACEABILITY.value:
            matrix = result.artifacts.get("traceability_matrix", [])
            links = []
            for item in matrix:
                requirement = item["requirement_id"]
                verification = item["verification_id"]
                if not item.get("evidence") or float(item.get("confidence", 0.0)) < float(self.profile.get("traceability_threshold", 0.75)):
                    continue
                evidence = item.get("evidence", evidence)
                origin = item.get("origin", "direct")
                review_status = item.get("review_status", "required")
                links.extend([
                    TraceabilityLink(f"LINK-{requirement}", requirement, verification, "requirement_to_test", origin=origin, confidence=float(item.get("confidence", result.confidence)), evidence=evidence, review_status=review_status),
                ])
            state.generated_artifacts["traceability_links"] = [asdict(link) for link in links]
        if state.current_state == WorkflowState.GENERATION.value:
            state.generated_artifacts.update(result.artifacts)
        if result.human_review_required:
            kind = {"validation": "schema_mapping", "compliance": "compliance", "traceability": "traceability_link", "generation": "generated_artifact", "assistant": "insufficient_evidence"}.get(state.current_state, state.current_state)
            self._review(state, kind, result.findings or result.artifacts, evidence)
            order = list(self.AGENTS)
            index = order.index(state.current_state)
            state.next_state = order[index + 1] if index + 1 < len(order) else WorkflowState.REPORTING.value
            previous = state.current_state
            state.current_state = WorkflowState.WAITING_FOR_REVIEW.value
            self._audit(state, "state_transition", metadata={"from": previous, "to": state.current_state, "resume": state.next_state})
        else:
            order = list(self.AGENTS)
            index = order.index(state.current_state)
            self._transition(state, order[index + 1] if index + 1 < len(order) else WorkflowState.REPORTING.value)

    def step(self, state: AgentState) -> AgentState:
        if state.cancelled:
            state.current_state, state.final_status = WorkflowState.CANCELLED.value, "cancelled"
            return state
        if state.steps >= self.limits.max_steps:
            state.errors.append("maximum workflow steps exceeded")
            state.current_state = WorkflowState.FAILED.value
            state.final_status = "failed"
            self.jobs.save(JobRecord(state.job_id, state.project, WorkflowState.FAILED.value, state=state.to_dict(), error=state.errors[-1]))
            return state
        state.final_status = "running"
        if state.current_state == WorkflowState.QUEUED.value:
            self._transition(state, WorkflowState.DOCUMENT_UNDERSTANDING.value)
        elif state.current_state == WorkflowState.DOCUMENT_UNDERSTANDING.value:
            self._run_understanding(state)
        elif state.current_state in self.AGENTS:
            self._run_agent(state)
        elif state.current_state == WorkflowState.REPORTING.value:
            state.generated_artifacts["report"] = build_report(state)
            self._transition(state, WorkflowState.COMPLETED.value)
            state.final_status = "completed"
        elif state.current_state == WorkflowState.WAITING_FOR_REVIEW.value:
            if any(task.status == "open" for task in state.review_tasks):
                state.final_status = "waiting-for-review"
                return state
            self._transition(state, self._resume_after_review(state))
        state.steps += 1
        status = "waiting-for-review" if state.current_state == WorkflowState.WAITING_FOR_REVIEW.value else ("completed" if state.current_state == WorkflowState.COMPLETED.value else ("failed" if state.current_state == WorkflowState.FAILED.value else "running"))
        state.final_status = status
        self.jobs.save(JobRecord(state.job_id, state.project, status, min(1.0, state.steps / 8), state=state.to_dict(), attempts=max(1, state.retry_count + 1), error=state.errors[-1] if state.errors else None))
        return state

    def _resume_after_review(self, state: AgentState) -> str:
        if any(task.decision == "reject" for task in state.review_tasks):
            state.warnings.append("one or more review proposals were rejected")
        corrections = [task for task in state.review_tasks if task.decision == "correct" and task.correction is not None]
        if corrections:
            state.smartx_artifacts.setdefault("corrections", []).extend(task.correction for task in corrections)
        for task in state.review_tasks:
            self._audit(state, "human_decision", metadata={"review_id": task.id, "decision": task.decision, "reviewer": task.reviewer, "comment_count": len(task.comments)})
        if state.next_state and state.next_state not in {WorkflowState.WAITING_FOR_REVIEW.value, WorkflowState.COMPLETED.value}:
            return state.next_state
        if state.agent_results:
            last = next(reversed(state.agent_results))
            order = list(self.AGENTS)
            if last in order:
                index = order.index(last)
                return order[index + 1] if index + 1 < len(order) else WorkflowState.REPORTING.value
        return WorkflowState.VALIDATION.value

    def run(self, state: AgentState, *, timeout: float | None = None) -> AgentState:
        started = time.monotonic()
        while state.current_state not in {WorkflowState.COMPLETED.value, WorkflowState.FAILED.value, WorkflowState.CANCELLED.value}:
            if time.monotonic() - started > (timeout if timeout is not None else self.limits.timeout_seconds):
                state.errors.append("workflow timeout exceeded")
                state.current_state = WorkflowState.FAILED.value
                state.final_status = "failed"
                break
            self.step(state)
            if state.current_state == WorkflowState.WAITING_FOR_REVIEW.value and any(task.status == "open" for task in state.review_tasks):
                break
        return state

    def resume(self, job_id: str) -> AgentState:
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        return self.run(AgentState.from_dict(job.state))

    def retry(self, job_id: str) -> AgentState:
        job = self.jobs.retry(job_id)
        state = AgentState.from_dict(job.state)
        state.retry_count += 1
        state.cancelled = False
        return self.run(state)

    def cancel(self, state: AgentState) -> AgentState:
        state.cancelled = True
        state.current_state, state.final_status = WorkflowState.CANCELLED.value, "cancelled"
        self.jobs.save(JobRecord(state.job_id, state.project, state.current_state, state=state.to_dict()))
        return state

    def decide(self, state: AgentState, task_id: str, decision: str, reviewer: str, comment: str = "", correction: Any = None) -> AgentState:
        task = self.reviews.decide(task_id, decision, reviewer, comment, correction)
        for local in state.review_tasks:
            if local.id == task.id:
                local.__dict__.update(task.__dict__)
        state.final_status = "queued"
        if state.current_state == WorkflowState.WAITING_FOR_REVIEW.value and not any(item.status == "open" for item in state.review_tasks):
            state.current_state = self._resume_after_review(state)
        self._audit(state, "human_decision", metadata={"review_id": task_id, "decision": decision, "reviewer": reviewer, "comment": comment, "correction_hash": _hash(correction) if correction is not None else ""})
        self.jobs.save(JobRecord(state.job_id, state.project, state.current_state, state=state.to_dict()))
        return state


def build_report(state: AgentState) -> dict[str, Any]:
    document = state.smartx_artifacts.get("document", {})
    return {
        "executive_summary": {"title": document.get("title", "SmartX report"), "status": state.final_status, "confidence": state.confidence, "review_required": bool(state.review_tasks)},
        "inventory": {"input_artifact_ids": state.input_artifact_ids, "generated_artifacts": list(state.generated_artifacts)},
        "configuration": {"project": state.project, "profile": state.profile},
        "findings": state.findings,
        "compliance_support": state.agent_results.get("compliance", {}),
        "traceability": state.generated_artifacts.get("traceability_links", []),
        "artifacts": state.generated_artifacts,
        "citations": state.citations + state.retrieved_knowledge,
        "decisions": [asdict(task) for task in state.review_tasks],
        "audit_metadata": {"job_id": state.job_id, "events": len(state.execution_history), "audit_hash": _hash([asdict(event) for event in state.execution_history])},
    }


def report_csv(report: dict[str, Any]) -> str:
    rows = report.get("findings", [])
    keys = sorted({key for row in rows if isinstance(row, dict) for key in row}) or ["status"]
    return "\n".join([",".join(keys)] + [",".join(json.dumps(row.get(key, ""), default=str) for key in keys) for row in rows]) + "\n"


def report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, default=str)


def filter_traceability(report_or_links: dict[str, Any] | list[dict[str, Any]], *, link_type: str | None = None, review_status: str | None = None, minimum_confidence: float = 0.0) -> list[dict[str, Any]]:
    links = report_or_links if isinstance(report_or_links, list) else report_or_links.get("traceability", [])
    return [link for link in links if (link_type is None or link.get("link_type") == link_type) and (review_status is None or link.get("review_status") == review_status) and float(link.get("confidence", 0.0)) >= minimum_confidence]


def traceability_csv(links: list[dict[str, Any]]) -> str:
    return report_csv({"findings": links})


def traceability_excel(links: list[dict[str, Any]]) -> bytes:
    return report_excel({"findings": links})


def report_excel(report: dict[str, Any]) -> bytes:
    try:
        from io import BytesIO
        import pandas as pd
        target = BytesIO()
        pd.DataFrame(report.get("findings", [])).to_excel(target, index=False)
        return target.getvalue()
    except Exception:
        return report_csv(report).encode("utf-8")


def report_pdf(report: dict[str, Any]) -> bytes | None:
    try:
        from io import BytesIO
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        target = BytesIO()
        page = canvas.Canvas(target, pagesize=letter)
        page.drawString(40, 750, str(report.get("executive_summary", {})))
        page.drawString(40, 730, f"Findings: {len(report.get('findings', []))}")
        page.save()
        return target.getvalue()
    except Exception:
        return None
