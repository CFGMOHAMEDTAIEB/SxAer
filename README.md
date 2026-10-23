# SmartX Developer Architecture

Milestone 2 provides evidence-first aerospace engineering assistance with persistent, isolated knowledge bases. It is not a certification tool and never represents generated content as approved compliance evidence.

## Windows setup

From PowerShell in the repository directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell execution policy blocks activation, run `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` and use that interpreter directly.

## Run

From the repository root:

```powershell
py -m streamlit run ui\streamlit_app.py
pytest -q
python -m compileall agents llm rag smartx ui tests
```

From the `ui` directory:

```powershell
cd ui
py -m streamlit run streamlit_app.py
```

The app works without API keys using deterministic fallback. ChromaDB is used when it can initialize; otherwise SmartX uses the clearly marked local JSON fallback in the same persistence directory.

## Providers and configuration

Select `deterministic`, `openai`, `azure_openai`, or `ollama` in the UI. Secrets are read only from environment variables or Streamlit secrets; do not put keys in source files.

```powershell
$env:SMARTX_LLM_PROVIDER="openai"
$env:SMARTX_LLM_ENDPOINT="https://api.openai.com"
$env:SMARTX_LLM_API_KEY="<set locally, do not commit>"
$env:SMARTX_LLM_MODEL="gpt-4o-mini"
```

```powershell
$env:SMARTX_LLM_PROVIDER="azure_openai"
$env:AZURE_OPENAI_ENDPOINT="https://<resource>.openai.azure.com"
$env:AZURE_OPENAI_API_KEY="<set locally, do not commit>"
$env:AZURE_OPENAI_API_VERSION="2024-10-21"
$env:SMARTX_LLM_MODEL="<deployment-name>"
```

```powershell
$env:SMARTX_LLM_PROVIDER="ollama"
$env:OLLAMA_ENDPOINT="http://localhost:11434"
$env:OLLAMA_MODEL="llama3.2"
```

Set `$env:SMARTX_CHROMA_DIR="C:\path\to\smartx-data"` to choose the persistent directory. Collection names are isolated by sanitized project and profile, for example `smartx_customer_a_airbus`. Profiles include generic, do178c, gt44, airbus, safran, and user-created names.

The Python API accepts `persist_directory` as the public persistence keyword (the existing `persist_dir` keyword remains supported), for example `KnowledgeBase(persist_directory="C:\path\to\smartx-data", project="customer-a", profile="airbus")`.

## Knowledge management

The UI accepts PDF, DOCX, TXT, MD, JSON, XML, CSV, XLSX, and XLS files plus project rules/guidance. Documents are SHA-256 deduplicated, chunked, and stored with filename, hash, project/profile, extraction method, confidence, and line/page/sheet metadata where available. Use the Knowledge Base section to inspect documents/chunks, test retrieval, clear, or rebuild the current collection.

## Milestone 3 workflow

`core/milestone3.py` provides a typed, local state machine equivalent to the
approved orchestration graph. It runs Document Understanding, Validation,
Compliance, Traceability, Generation, Assistant, and Reporting states. It
pauses at persisted review tasks for low confidence, schema mappings,
compliance, links, generated artifacts, insufficient evidence, and rule
conflicts; reviewers can approve, reject, or correct a proposal and resume the
same job. Jobs are atomic JSON records under `.smartx_jobs`, isolated by
project, and support interrupted-job recovery, cancellation, retries, and
step/time/input/token/cost limits.

Audit events contain state transitions, hashes, citations, versions, and human
decisions. Keys are never placed in audit records. Traceability links support
requirement-to-design, design-to-code, code-to-test, and requirement-to-test
relationships. The UI includes Review Queue and Evaluation views and the
reporting API supports JSON/CSV/Excel plus optional PDF export.

## Limitations and next milestone

Optional readers and remote providers can fail and are surfaced as human-review states. Chroma embedding availability varies by environment; the local lexical fallback is deterministic and persistent but less semantically capable. Retrieved content is untrusted and is delimited in LLM prompts. The Milestone 3 engine is intentionally local and sequential rather than distributed; review authorization is application-level, not enterprise identity. PDF output requires optional ReportLab. No output is certification evidence.

Next Milestone 4: distributed workers and queue integration, enterprise
identity/RBAC, policy versioning, richer semantic retrieval, and production
observability with configurable retention.

## Validation workspace

Milestone 4 adds a Validation Workspace in the Streamlit sidebar. Select
**Validation workspace**, load the built-in regression dataset, add or replace
cases with source text and expected SmartX JSON, then run evaluation. Reports
include extraction precision/recall, classification accuracy, validation
false-positive/false-negative rates, traceability metrics, citation
correctness, human-review rate, fallback rate, processing time, and detected
weaknesses. Evaluation reports can be downloaded as JSON, Excel (or a CSV
fallback), and PDF when ReportLab is installed.

The editable profile configuration is stored in
`configs/validation_profiles.json`. Generic and DO-178C-oriented rules are
transparent examples. GT44 entries are explicitly marked `sample_rules` and
are not proprietary requirements.

The built-in regression corpus uses deterministic TXT, XML, JSON, Markdown,
and C samples. PDF, DOCX, and Excel cases can be added through the workspace
when their optional readers are installed.

## Milestone 5 understanding and evaluation

Milestone 5 adds deterministic autonomous understanding: content-aware artifact
classification, section/paragraph/code-symbol discovery, profile suggestions
with rationale and evidence, and canonical JSON translation. Headings,
decorative rows, and empty rows are ignored; spreadsheet aliases such as
`Req ID`, `Requirement ID`, `Description`, and `Text` are normalized while
unknown artifacts are preserved for review. Mixed artifact types are reported
in provenance metadata.

Validation supports `exact`, `required-fields`, `normalized`, and `semantic`
comparison modes. Semantic content is compared separately from technical
metadata. Validation FP/FN rates are calculated from false-positive and
false-negative counts, and citation checks can require chunk ID, source
filename, location, and minimum score. Reports retain legacy metric names and
also include `before_after_compatible` metadata.

Planner and Critic outputs are typed and deterministic. A critic can request
one repair cycle; unresolved issues become human-review tasks. Traceability
links require matching retrieved evidence above the configured
`traceability_threshold`, are deduplicated, explain their match, and identify
direct, inferred, or LLM-proposed origins.

Learned mappings and golden examples use `LearnedCorrectionsStore` under
`.smartx_learning/` and are isolated by project and customer. They can be
listed, disabled, deleted, and reused only within the same isolation scope.
They are local engineering aids, not certification evidence.

The Processing UI's Understanding tab includes an optional Inspector for
classification, structure, profile rationale, evidence, planner output,
critic output, mappings, and citations. The ordinary upload flow remains
unchanged and works without API keys.
"# SxAer" 
