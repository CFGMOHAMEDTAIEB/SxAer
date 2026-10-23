"""Streamlit entrypoint for the SmartX MVP.

The path bootstrap is intentional: Streamlit executes this file with ``ui``
as the import context when launched from that directory.
"""

import json
import csv
import sys
from dataclasses import asdict
from io import BytesIO
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
	sys.path.insert(0, str(REPOSITORY_ROOT))

try:
	import streamlit as st
except ImportError:  # Allows compile/import checks without UI dependencies.
	st = None

from llm.router import LLMRouter
from rag.retriever import SessionRetriever
from smartx.pipeline import SmartXPipeline
from core.milestone3 import JobRecord, SmartXWorkflow, WorkflowLimits, filter_traceability, report_csv, report_excel, report_json, report_pdf
from validation.configuration import ProfileConfiguration
from validation.evaluator import ValidationCase, ValidationDataset, ValidationEvaluator, build_regression_dataset
from validation.learning import LearnedCorrectionsStore
from agents.planner_agent import PlannerAgent
from agents.critic_agent import CriticAgent


SUPPORTED = ["txt", "md", "json", "xml", "csv", "xlsx", "xls", "docx", "pdf", "c", "h", "cpp", "cc", "hpp"]


def _rows(result: dict) -> list[dict]:
	rows = []
	for entry in result.get("results", []):
		for finding in entry.get("findings", []):
			rows.append({"agent": entry["agent"], **finding})
	return rows


def _download_csv(result: dict) -> str:
	rows = _rows(result)
	columns = sorted({key for row in rows for key in row}) or ["agent", "status"]
	from io import StringIO
	buffer = StringIO()
	writer = csv.DictWriter(buffer, fieldnames=columns)
	writer.writeheader()
	writer.writerows({key: json.dumps(row.get(key, ""), ensure_ascii=False) if isinstance(row.get(key), (dict, list)) else row.get(key, "") for key in columns} for row in rows)
	return buffer.getvalue()


def _download_json(result: dict) -> str:
	return json.dumps(result, indent=2, ensure_ascii=False, default=str)


def _download_excel(result: dict) -> bytes:
	"""Return an XLSX when available, otherwise a UTF-8 CSV payload."""
	rows = _rows(result)
	try:
		import pandas as pd  # type: ignore
		target = BytesIO()
		pd.DataFrame(rows).to_excel(target, index=False, engine="openpyxl")
		return target.getvalue()
	except Exception:
		return _download_csv(result).encode("utf-8")


def _download_report(result: dict) -> str:
	document = result.get("document", {})
	lines = [
		f"SmartX review report: {document.get('title', 'Untitled')}",
		"=" * 40,
		f"Profile: {document.get('profile', 'generic')}",
		f"Confidence: {document.get('confidence', 0):.0%}",
		f"Human review required: {result.get('human_review_required', True)}",
		"",
	]
	for entry in result.get("results", []):
		lines.append(f"[{entry.get('agent', 'unknown')}] status={entry.get('status', 'unknown')}")
		for finding in entry.get("findings", []):
			lines.append(f"- {json.dumps(finding, ensure_ascii=False, default=str)}")
		for name, artifact in entry.get("artifacts", {}).items():
			lines.append(f"- {name}: {json.dumps(artifact, ensure_ascii=False, default=str)}")
	return "\n".join(lines) + "\n"


def _traceability_rows(result: dict) -> list[dict]:
	return filter_traceability(result.get("traceability", result.get("artifacts", {}).get("traceability_links", [])))


def render_validation_workspace() -> None:
	st.header("Validation workspace")
	st.caption("Evaluate SmartX against expected outputs. Results are quality indicators, not certification evidence.")
	config = ProfileConfiguration()
	tabs = st.tabs(["Dataset", "Run evaluation", "Profile rules"])
	with tabs[0]:
		if st.button("Load built-in regression dataset"):
			st.session_state.validation_dataset = build_regression_dataset()
		dataset = st.session_state.get("validation_dataset", ValidationDataset("new-dataset"))
		st.write(f"**{dataset.name}** — {len(dataset.cases)} case(s)")
		st.dataframe([{"name": case.name, "filename": case.filename, "profile": case.profile} for case in dataset.cases], width="stretch")
		with st.form("validation_case"):
			name = st.text_input("Case name", value="case-1")
			filename = st.text_input("Filename", value="requirements.txt")
			text = st.text_area("Source content", value="The system shall record events.")
			expected = st.text_area("Expected SmartX JSON", value='{"document_type":"requirement","items":[]}')
			if st.form_submit_button("Add or replace case"):
				try:
					dataset.add_case(ValidationCase(name, filename, text.encode("utf-8"), json.loads(expected)))
					st.session_state.validation_dataset = dataset
					st.success("Case saved in the current session.")
				except json.JSONDecodeError as exc:
					st.error(f"Expected SmartX JSON is invalid: {exc}")
	with tabs[1]:
		dataset = st.session_state.get("validation_dataset", build_regression_dataset())
		if st.button("Run dataset evaluation"):
			st.session_state.validation_report = ValidationEvaluator().evaluate(dataset)
		report = st.session_state.get("validation_report")
		if report:
			st.metric("Cases", report["case_count"])
			st.json(report["metrics"])
			if report["weaknesses"]:
				st.warning("Detected weaknesses: " + "; ".join(report["weaknesses"]))
			st.download_button("Download evaluation JSON", ValidationEvaluator.report_json(report), "smartx-evaluation.json", "application/json")
			st.download_button("Download evaluation Excel", ValidationEvaluator.report_excel(report), "smartx-evaluation.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
			pdf = ValidationEvaluator.report_pdf(report)
			if pdf:
				st.download_button("Download evaluation PDF", pdf, "smartx-evaluation.pdf", "application/pdf")
	with tabs[2]:
		profile = st.selectbox("Profile", config.profiles(), key="validation-profile")
		profile_data = config.get(profile)
		rules_json = st.text_area("Rules JSON", json.dumps(profile_data.get("rules", []), indent=2), height=180)
		threshold = st.slider("Confidence threshold", 0.0, 1.0, float(profile_data.get("confidence_threshold", 0.75)))
		if st.button("Save profile configuration"):
			try:
				config.update(profile, {"rules": json.loads(rules_json), "confidence_threshold": threshold, "human_review_threshold": threshold})
				st.success("Profile configuration saved.")
			except json.JSONDecodeError as exc:
				st.error(f"Rules JSON is invalid: {exc}")


def process_sources(profile: str, provider: str, sources: list[tuple[str, bytes]], retriever: SessionRetriever) -> list[dict]:
	"""Process multiple pasted/uploaded sources without requiring an external provider."""
	processed = []
	for name, data in sources:
		retriever.ingest_file(name, data)
		workflow = SmartXWorkflow(
			profile=retriever.store.profile_config if hasattr(retriever.store, "profile_config") else {},
			llm_router=LLMRouter(provider),
			retriever=retriever,
			storage_dir=Path(retriever.store.persist_dir).parent / ".smartx_jobs",
			project=retriever.project,
		)
		state = workflow.new_state("Process uploaded engineering evidence", [(name, data)], profile=profile)
		state.retrieved_knowledge = retriever.retrieve(name, limit=5)
		state.citations = list(state.retrieved_knowledge)
		workflow.jobs.save(JobRecord(state.job_id, state.project, state.final_status, state=state.to_dict()))
		state = workflow.run(state)
		results = [{"agent": key, **value} for key, value in state.agent_results.items()]
		report = state.generated_artifacts.get("report", {})
		processed.append({
			"document": state.smartx_artifacts.get("document", {}),
			"results": results,
			"human_review_required": bool(state.review_tasks),
			"review_tasks": [asdict(task) for task in state.review_tasks],
			"audit": [asdict(event) for event in state.execution_history],
			"traceability": state.generated_artifacts.get("traceability_links", []),
			"report": report,
			"orchestration_job_id": state.job_id,
			"orchestration_status": state.final_status,
		})
	return processed


def main() -> None:
	if st is None:
		raise RuntimeError("Install Streamlit to run the SmartX UI")
	st.set_page_config(page_title="SmartX Developer Architecture", page_icon="✈️", layout="wide")
	st.title("SmartX Developer Architecture")
	st.caption("Evidence-first requirements understanding for aerospace development workflows")
	with st.sidebar:
		st.header("Processing")
		project = st.text_input("Project isolation", value="default")
		profile = st.selectbox("Profile", ["generic", "do178c", "gt44", "airbus", "safran", "user-created"])
		if profile == "user-created":
			profile = st.text_input("User-created profile name", value="custom")
		persist_directory = st.text_input("Chroma persistence directory", value=".smartx_chroma")
		st.session_state.retriever = SessionRetriever(persist_directory=persist_directory, project=project, profile=profile)
		provider = st.selectbox("LLM provider", ["deterministic", "openai", "azure_openai", "ollama"])
		uploaded = st.file_uploader("Upload sources", type=SUPPORTED, accept_multiple_files=True)
		pasted = st.text_area("Paste requirements or source text", height=160, placeholder="The system shall ...")
		st.info("Supported: TXT, MD, JSON, XML, CSV, XLSX/XLS, DOCX, PDF, C/C++")
		if st.button("Test provider connection"):
			st.json(LLMRouter(provider).connection_test())
		st.caption("Tool access is limited to the selected local provider and authorized retriever.")
		st.caption(f"Storage backend: {st.session_state.retriever.store.backend} · collection: {st.session_state.retriever.store.collection_name}")
		workspace = st.selectbox("Workspace", ["Processing", "Validation workspace"])
	if workspace == "Validation workspace":
		render_validation_workspace()
		return
	sources = [(item.name, item.getvalue()) for item in (uploaded or [])]
	if pasted.strip():
		sources.insert(0, ("pasted_text.txt", pasted.encode("utf-8")))
	if sources:
		try:
			results = process_sources(profile, provider, sources, st.session_state.retriever)
			result = results[0] if len(results) == 1 else {"documents": [item["document"] for item in results], "document": {"title": f"{len(results)} sources"}, "results": [entry for item in results for entry in item["results"]], "human_review_required": any(item.get("human_review_required") for item in results)}
			st.success(f"Processed {len(sources)} source(s)")
			if result.get("human_review_required"):
				st.warning("Human review required: extraction or analysis confidence is below the automatic acceptance threshold.")
			tabs = st.tabs(["Understanding", "Validation", "Compliance", "Traceability", "Generation", "Assistant", "Review Queue", "Audit", "Evaluation", "Reports"])
			with tabs[0]:
				confidence = result.get("document", {}).get("confidence", 0)
				st.metric("Confidence", f"{confidence:.0%}")
				document = result.get("document", result)
				understanding = document.get("metadata", {}).get("understanding", {})
				st.subheader("Understanding Inspector")
				st.json({"classification": understanding.get("classification", document.get("document_type")), "structure": understanding.get("structure", {}), "profile_suggestion": understanding.get("profile_suggestion", {}), "evidence": understanding.get("evidence", [])})
				st.json(document)
				if st.checkbox("Show deterministic plan and critic", key="show-planner"):
					plan = PlannerAgent().plan("analyze uploaded engineering evidence", understanding)
					st.json(plan.to_dict())
					st.json(CriticAgent().review(plan, document).to_dict())
			for tab, agent_name in zip(tabs[1:5], ["validation", "compliance", "traceability", "generation"]):
				with tab:
					entries = [entry for entry in result["results"] if entry["agent"] == agent_name]
					st.json(entries[0] if entries else {})
			with tabs[3]:
				links = _traceability_rows(result)
				st.metric("Graph links", len(links))
				if links:
					st.dataframe(links, width="stretch")
					st.download_button("Download traceability CSV", report_csv({"findings": links}), "traceability.csv", "text/csv")
					st.download_button("Download traceability Excel", report_excel({"findings": links}), "traceability.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
			with tabs[5]:
				question = st.text_input("Ask about this session")
				if question:
					context = st.session_state.retriever.retrieve(question)
					st.write(LLMRouter(provider).complete(f"Question: {question}\nEvidence: {context}"))
			with tabs[6]:
				st.caption("Review decisions are persisted locally and never treated as certification approval.")
				for entry in result.get("review_tasks", []):
					st.write(f"**{entry.get('kind', 'review')}** · {entry.get('status', 'open')} · {entry.get('source', '')}")
					st.json({"proposal": entry.get("proposal"), "citations": entry.get("citations", [])})
			with tabs[7]:
				st.subheader("Audit timeline")
				st.dataframe(result.get("audit", result.get("audit_metadata", {})), width="stretch")
			with tabs[8]:
				findings = _rows(result)
				st.metric("Findings", len(findings))
				st.metric("Citation coverage", f"{sum(bool(row.get('citations')) for row in findings) / len(findings):.0%}" if findings else "0%")
				st.subheader("Mappings and citations")
				st.json({"citations": result.get("report", {}).get("citations", result.get("citations", [])), "traceability": _traceability_rows(result)})
			with tabs[9]:
				report = result.get("report", result)
				st.download_button("Download JSON report", report_json(report), "smartx-report.json", "application/json")
				st.download_button("Download findings CSV", report_csv(report), "smartx-findings.csv", "text/csv")
				st.download_button("Download Excel report", report_excel(report), "smartx-report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
				pdf = report_pdf(report)
				if pdf:
					st.download_button("Download PDF report", pdf, "smartx-report.pdf", "application/pdf")
				else:
					st.info("PDF export is unavailable; install the optional ReportLab dependency to enable it.")
				st.download_button("Download human-readable report", _download_report(result), "smartx-report.txt", "text/plain")
		except Exception as exc:
			st.error(f"Unable to process document safely: {exc}")
	else:
		st.subheader("Persistent knowledge base")
		kb_tabs = st.tabs(["Documents", "Chunks", "Retrieval test", "Maintenance"])
		with kb_tabs[0]:
			st.caption("Authorized collections")
			st.json(st.session_state.retriever.list_collections())
			st.json(st.session_state.retriever.list_documents())
		with kb_tabs[1]:
			st.json(st.session_state.retriever.preview())
		with kb_tabs[2]:
			query = st.text_input("Search authorized collection")
			if query:
				st.json(st.session_state.retriever.retrieve(query))
		with kb_tabs[3]:
			col1, col2 = st.columns(2)
			with col1:
				if st.button("Clear current collection"):
					st.session_state.retriever.clear()
					st.success("Current collection cleared.")
			with col2:
				if st.button("Rebuild current collection"):
					st.session_state.retriever.rebuild()
					st.success("Current collection rebuilt; upload sources to index it again.")
		st.markdown("Upload a source document to begin Document Understanding, Validation, Compliance, Traceability, Generation, and Assistant workflows.")


if __name__ == "__main__":
	main()
