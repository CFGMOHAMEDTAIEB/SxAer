from smartx.models import AgentResult, SmartXDocument


class ComplianceAgent:
	def __init__(self, profile=None, llm_router=None, evidence=None):
		self.profile, self.llm_router, self.evidence = profile or {}, llm_router, evidence or []

	def run(self, document: SmartXDocument) -> AgentResult:
		rules = self.profile.get("rules", [])
		if not self.evidence:
			return AgentResult("compliance", status="review", confidence=0.2, findings=[{"status": "review", "message": "insufficient authorized evidence", "citations": []}], human_review_required=True)
		findings = [{"rule": rule, "status": "review", "evidence": document.provenance, "citations": self.evidence} for rule in rules]
		return AgentResult("compliance", confidence=0.85 if rules else 0.7, findings=findings, artifacts={"citations": self.evidence}, human_review_required=True)
