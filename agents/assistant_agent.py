from smartx.models import AgentResult, SmartXDocument


class AssistantAgent:
	def __init__(self, profile=None, llm_router=None, evidence=None):
		self.profile, self.llm_router, self.evidence = profile or {}, llm_router, evidence or []

	def run(self, document: SmartXDocument, question: str = "") -> AgentResult:
		if not self.evidence:
			return AgentResult("assistant", status="review", confidence=0.2, artifacts={"answer": "insufficient authorized evidence", "citations": []}, human_review_required=True)
		answer = f"Document {document.title} contains {len(document.items)} requirement item(s) under the {document.profile} profile."
		if question:
			answer += " Use the traceability and compliance findings for evidence-backed review."
		if self.llm_router:
			structured = self.llm_router.complete_json(f"Question: {question}\nEVIDENCE: {self.evidence}\nProvide an answer and citations.", ["answer", "citations"])
			answer = structured.get("answer", answer)
			citations = structured.get("citations") or self.evidence
		else:
			citations = self.evidence
		return AgentResult("assistant", confidence=0.75, artifacts={"answer": answer, "citations": citations}, human_review_required=True)
