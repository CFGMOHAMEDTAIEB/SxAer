import subprocess
import sys
from pathlib import Path

from core.milestone3 import WorkflowState, route_request


def test_route_policy_covers_review_and_completion_paths():
    assert route_request(current=WorkflowState.VALIDATION.value, request="compliance review").target == WorkflowState.COMPLIANCE.value
    assert route_request(current=WorkflowState.GENERATION.value, approved=True).reason == "approved_generation"
    assert route_request(current=WorkflowState.REPORTING.value).target == WorkflowState.COMPLETED.value
    assert route_request(current=WorkflowState.VALIDATION.value, valid_json=False).reason == "invalid_json_repair"
    assert route_request(current=WorkflowState.COMPLIANCE.value, evidence=False).requires_review


def test_streamlit_entrypoint_imports_from_ui_directory():
    repository = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "import streamlit_app; import llm; print('ok')"],
        cwd=repository / "ui",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout