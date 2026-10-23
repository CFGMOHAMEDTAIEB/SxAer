import json
from pathlib import Path

from core.milestone3 import (
    AgentState,
    JobStore,
    SmartXWorkflow,
    TraceabilityLink,
    WorkflowLimits,
    WorkflowState,
    build_report,
    report_excel,
    report_pdf,
)


def _approve_open(workflow, state):
    while True:
        open_tasks = [task for task in state.review_tasks if task.status == "open"]
        if not open_tasks:
            return workflow.run(state)
        for task in open_tasks:
            workflow.decide(state, task.id, "approve", "test-reviewer", "approved for engineering review")
        state = workflow.run(state)


def test_typed_state_machine_pauses_and_resumes_with_audit(tmp_path):
    workflow = SmartXWorkflow(storage_dir=tmp_path, project="customer-a", limits=WorkflowLimits(max_steps=40))
    state = workflow.new_state("analyze requirements", [("req.txt", b"The system shall log events.")])
    state = workflow.run(state)
    assert state.current_state == WorkflowState.WAITING_FOR_REVIEW.value
    assert state.review_tasks
    assert any(event.event == "state_transition" for event in state.execution_history)
    state = _approve_open(workflow, state)
    assert state.current_state == WorkflowState.COMPLETED.value
    assert state.generated_artifacts["report"]["audit_metadata"]["events"]


def test_review_rejection_and_correction_are_persisted(tmp_path):
    workflow = SmartXWorkflow(storage_dir=tmp_path, project="customer-a")
    state = workflow.new_state("review", [("empty.txt", b"")])
    state = workflow.run(state)
    task = state.review_tasks[0]
    workflow.decide(state, task.id, "correct", "reviewer", "use corrected text", {"text": "The system shall operate."})
    persisted = workflow.reviews.list()[0]
    assert persisted.decision == "correct"
    assert persisted.comments[0]["author"] == "reviewer"


def test_restart_recovery_and_project_isolation(tmp_path):
    workflow = SmartXWorkflow(storage_dir=tmp_path, project="a")
    state = workflow.new_state("recover", [("req.txt", b"The system shall work.")])
    state.current_state = WorkflowState.VALIDATION.value
    workflow.jobs.save(__import__("core").JobRecord(state.job_id, "a", "running", state=state.to_dict()))
    recovered = workflow.jobs.recover_interrupted()
    assert recovered and recovered[0].status == "queued"
    assert JobStore(tmp_path, "b").get(state.job_id) is None


def test_limits_and_traceability_contract(tmp_path):
    workflow = SmartXWorkflow(storage_dir=tmp_path, project="a", limits=WorkflowLimits(max_input_bytes=2))
    try:
        workflow.new_state("too large", [("x.txt", b"123")])
    except ValueError as exc:
        assert "size" in str(exc)
    else:
        raise AssertionError("size limit was not enforced")
    link = TraceabilityLink("L1", "REQ-1", "TEST-1", "requirement_to_test", confidence=0.8)
    assert link.link_type == "requirement_to_test"


def test_report_exports_and_no_keys(tmp_path):
    workflow = SmartXWorkflow(storage_dir=tmp_path, project="a")
    state = AgentState("job-1", "report", project="a")
    report = build_report(state)
    assert {"executive_summary", "inventory", "configuration", "findings", "audit_metadata"} <= set(report)
    assert report_excel(report)
    assert report_pdf(report) is None or report_pdf(report).startswith(b"%PDF")
    assert "api_key" not in json.dumps(report).lower()
