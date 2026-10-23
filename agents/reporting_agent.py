from core.milestone3 import build_report
from smartx.models import AgentResult


class ReportingAgent:
    """Builds a review-oriented report without claiming certification."""

    def run(self, state) -> AgentResult:
        report = build_report(state)
        return AgentResult(
            "reporting",
            confidence=state.confidence,
            human_review_required=bool(state.review_tasks),
            artifacts={"report": report},
        )
