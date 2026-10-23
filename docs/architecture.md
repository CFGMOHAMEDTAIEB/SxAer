# Architecture

`Upload -> Extraction -> AgentState -> Persistent isolated RAG -> Resumable state machine -> Review Queue -> Reporting -> Downloads`

## Boundaries

- `smartx/extraction.py` contains all parsing and provenance hashing. Optional packages are imported only inside the format branch that needs them.
- `smartx/models.py`, `smartx/schema.py`, and `schemas/smartx_schema.json` define the stable normalized contract.
- `smartx/pipeline.py` is the public end-to-end entry point.
- `agents/` contains deterministic, evidence-linked agent implementations. The orchestrator always returns per-agent status, confidence, findings, artifacts, and review state.
- `llm/` exposes a small provider contract. Network providers are opt-in; failures fall back to a deterministic response.
- `rag/` provides persistent ChromaDB collections isolated by project/profile, with a clearly marked persistent JSON lexical fallback when Chroma or its embedding runtime is unavailable.
- `ui/streamlit_app.py` is a thin presentation layer with tabs and downloads.
- `core/milestone3.py` provides typed state, explicit transitions, local job and review stores, audit events, limits, traceability links, and report exports. It avoids a LangGraph dependency when unavailable.

## Knowledge isolation

Every retriever is constructed with a project and profile. It queries only its `smartx_<project>_<profile>` collection; no cross-customer collection search is performed. Upload hashes prevent duplicate documents. Retrieval results expose chunk ID, source filename, source locations, score, and metadata for citations.

## Review model

Low extraction confidence, optional-reader failures, missing requirement fields, and generated compliance/verification content set `human_review_required`. SmartX never represents draft generated output as approved certification evidence.

Milestone 3 review tasks are durable records with proposals, source/location,
citations, comments, timestamps, reviewer, and approve/reject/correct decisions.
The job resumes from the waiting state after a decision. Job records are
project-isolated JSON files and preserve enough state to recover interrupted
work without network services. Audit entries hash inputs and outputs and keep
retrieved citations and human decisions, but never plaintext credentials.

The traceability graph uses explicit links for `requirement_to_design`,
`design_to_code`, `code_to_test`, and `requirement_to_test`, including origin,
confidence, evidence, review status, and reviewer decision. Reporting
aggregates findings, compliance support, traceability, artifacts, citations,
decisions, and audit metadata.

## Validation workspace

`validation/evaluator.py` defines serializable validation datasets and cases.
Each case stores source bytes, expected SmartX JSON, expected findings, and
expected traceability links. The evaluator runs the existing pipeline without
an API key, compares normalized sets, calculates precision/recall and review
metrics, records weaknesses, and exports JSON, Excel/CSV fallback, or optional
PDF reports. `validation/configuration.py` stores editable profile rules and
confidence thresholds; GT44 rules are labeled samples only.

Milestone 5 extends this contract with `smartx/understanding.py`, typed
`PlannerAgent`/`CriticAgent` outputs, and `validation/learning.py`. Extraction
uses content heuristics and preserves unknown or mixed artifacts. Traceability
is evidence-backed and thresholded rather than synthetic. Evaluation supports
four comparison modes, semantic/technical separation, corrected FP/FN rates,
and citation identity/location/score validation. Learned corrections are
project/customer scoped and never cross isolation boundaries.

## Original logical flow

Agents:

- Validation Agent
- Traceability Agent
- Generation Agent
- Compliance Agent
- Assistant Agent

Knowledge Bases:

- DO178C
- GT44
- Safran
- Airbus
