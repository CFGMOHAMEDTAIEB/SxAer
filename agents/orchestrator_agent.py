from smartx.models import SmartXDocument
from .assistant_agent import AssistantAgent
from .compliance_agent import ComplianceAgent
from .generation_agent import GenerationAgent
from .traceability_agent import TraceabilityAgent
from .validation_agent import ValidationAgent


class OrchestratorAgent:
	def __init__(self, profile=None, llm_router=None, retriever=None):
		self.profile, self.llm_router, self.retriever = profile or {}, llm_router, retriever

	def run(self, document: SmartXDocument) -> dict:
		agents = [ValidationAgent, ComplianceAgent, TraceabilityAgent, GenerationAgent, AssistantAgent]
		evidence = self.retriever.retrieve(document.content or document.title, 5) if self.retriever else []
		results = [agent(self.profile, self.llm_router, evidence).run(document) for agent in agents]
		return {"document": document.to_dict(), "results": [result.to_dict() for result in results], "human_review_required": any(result.human_review_required for result in results) or document.human_review_required}
