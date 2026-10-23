from agents.critic_agent import CriticAgent
from agents.planner_agent import PlannerAgent
from agents.traceability_agent import TraceabilityAgent
from smartx.extraction import extract_document, split_requirements
from smartx.models import SmartXDocument
from smartx.understanding import UnderstandingService
from validation.evaluator import ValidationEvaluator, compare_values, validate_citations
from validation.learning import LearnedCorrectionsStore


def test_comparison_modes_and_correct_fp_fn():
    expected = [{"id": "R1", "text": "System shall log events", "technical": "expected"}]
    actual = [{"id": "different", "text": " system SHALL log events ", "technical": "actual"}]
    assert compare_values(expected, actual, "exact")[0] == 0
    assert compare_values(expected, actual, "normalized")[0] == 1
    assert compare_values(expected, actual, "semantic")[0] == 1
    report = ValidationEvaluator().evaluate_case(__import__("validation.evaluator", fromlist=["ValidationCase"]).ValidationCase("fp", "x.txt", b"The system shall log events.", expected_findings=[]))
    assert report["metrics"]["validation"]["false_positive_rate"] == 1


def test_unknown_and_mixed_artifacts_are_preserved():
    text, metadata, provenance = extract_document("notes.weird", b"# Heading\nThe system shall log events.\nvoid f() {}")
    assert metadata["unknown_format"] and provenance["source_name"] == "notes.weird"
    assert metadata["mixed_artifact_types"]
    assert [item["text"] for item in split_requirements(text)] == ["The system shall log events."]


def test_column_aliases_and_understanding_planner_critic():
    rows = [{"Req ID": "REQ-9", "Description": "The system must display status."}]
    items = split_requirements("", {"rows": rows})
    assert items[0]["id"] == "REQ-9"
    understanding = UnderstandingService().analyze("req.txt", items[0]["text"], {"artifact_type": "requirement"}, items)
    plan = PlannerAgent().plan("analyze", understanding.to_dict())
    assert plan.steps and plan.confidence > 0
    assert CriticAgent().review(plan, understanding.canonical_json).status == "accepted"


def test_traceability_requires_matching_evidence_and_deduplicates():
    document = SmartXDocument(items=[{"id": "REQ-1", "text": "system shall log events"}])
    evidence = [{"chunk_id": "c1", "text": "system shall log events", "score": 0.9, "metadata": {"filename": "design.txt", "line_start": 4}}] * 2
    result = TraceabilityAgent({"traceability_threshold": 0.75}, evidence=evidence).run(document)
    assert len(result.artifacts["traceability_matrix"]) == 1
    assert result.artifacts["traceability_matrix"][0]["chunk_id"] == "c1"
    assert not TraceabilityAgent({}, evidence=[]).run(document).artifacts["traceability_matrix"]


def test_citation_correctness_and_learning_isolation(tmp_path):
    actual = [{"chunk_id": "c1", "score": 0.9, "metadata": {"filename": "a.txt", "line_start": 2}}]
    assert validate_citations([{"chunk_id": "c1", "source": "a.txt", "location": {"line_start": 2}, "score": 0.8}], actual)["correctness"] == 1
    one = LearnedCorrectionsStore(tmp_path, "project-a", "customer-a")
    row = one.add("mapping", "Req ID", "requirement_id", golden=True)
    assert one.reuse("mapping", "Req ID")
    assert not LearnedCorrectionsStore(tmp_path, "project-b", "customer-b").reuse("mapping", "Req ID")
    assert one.disable(row["id"]) and not one.reuse("mapping", "Req ID")