from smartx.models import AgentResult, SmartXDocument


class TraceabilityAgent:
	def __init__(self, profile=None, llm_router=None, evidence=None):
		self.profile, self.llm_router, self.evidence = profile or {}, llm_router, evidence or []

	def run(self, document: SmartXDocument) -> AgentResult:
		threshold = float(self.profile.get("traceability_threshold", 0.75))
		links = []
		seen = set()
		for item in document.items:
			for citation in self.evidence:
				metadata = citation.get("metadata", {}) if isinstance(citation, dict) else {}
				score = float(citation.get("score", metadata.get("confidence", 0.0))) if isinstance(citation, dict) else 0.0
				if score < threshold:
					continue
				text = str(citation.get("text", "")) if isinstance(citation, dict) else ""
				if item.get("text", "").lower() not in text.lower() and not any(word in text.lower() for word in item.get("text", "").lower().split()[:3]):
					continue
				key = (item.get("id"), citation.get("chunk_id"), metadata.get("filename", citation.get("source", "")))
				if key in seen:
					continue
				seen.add(key)
				origin = "llm-proposed" if citation.get("origin") == "llm" else ("inferred" if citation.get("origin") == "inferred" else "direct")
				links.append({"requirement_id": item["id"], "source": metadata.get("filename", citation.get("source", "")), "verification_id": f"VER-{item['id']}", "chunk_id": citation.get("chunk_id"), "origin": origin, "confidence": score, "evidence": [citation], "explanation": f"Matched requirement text to cited chunk with score {score:.2f}.", "review_status": "required" if origin != "direct" or score < 0.9 else "not_required"})
		return AgentResult("traceability", confidence=max((link["confidence"] for link in links), default=0.3), human_review_required=any(link["review_status"] == "required" for link in links), artifacts={"traceability_matrix": links, "citations": self.evidence})
