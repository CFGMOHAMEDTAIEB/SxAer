from smartx.models import AgentResult, SmartXDocument


class ValidationAgent:
	def __init__(self, profile=None, llm_router=None, evidence=None):
		self.profile, self.llm_router, self.evidence = profile or {}, llm_router, evidence or []

	def run(self, document: SmartXDocument) -> AgentResult:
		findings = []
		for item in document.items:
			text = item.get("text", "")
			issues = []
			if len(text) < 12:
				issues.append("Requirement is unusually short")
			if not any(word in text.lower() for word in ("shall", "must", "should")):
				issues.append("No normative keyword detected")
			findings.append({"id": item.get("id"), "valid": not issues, "issues": issues})
		return AgentResult("validation", confidence=0.9 if document.items else 0.3, human_review_required=bool(document.warnings), findings=findings, artifacts={"citations": self.evidence})
