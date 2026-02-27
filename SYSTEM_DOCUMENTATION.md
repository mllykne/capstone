# AI-Powered Document Classification & Privacy Risk System
## Proof-of-Concept — System Documentation

**Version:** 1.0  
**Date:** February 2026  
**Classification:** Internal / PoC Reference  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Solution Overview & Architecture](#2-solution-overview--architecture)
3. [Technology Stack](#3-technology-stack)
4. [AI Classification Design](#4-ai-classification-design)
5. [RAG Design](#5-rag-design)
6. [Risk Scoring Framework](#6-risk-scoring-framework)
7. [Data Model & Storage](#7-data-model--storage)
8. [Security & Privacy Considerations](#8-security--privacy-considerations)
9. [Limitations of the Prototype](#9-limitations-of-the-prototype)
10. [Future Enhancements](#10-future-enhancements)

---

## 1. Executive Summary

### Purpose

Organisations storing documents in platforms like Microsoft SharePoint frequently lack visibility into what sensitive information those documents contain, how they are categorised, and where privacy risk is concentrated. Documents may sit in shared drives for years, containing personally identifiable information (PII), financial credentials, or legally sensitive content that the organisation has no systematic way of identifying.

This proof-of-concept (PoC) addresses that problem by demonstrating how an AI-assisted scanning pipeline can automatically read, classify, and risk-score documents at scale — surfacing sensitive content governance issues that would otherwise require expensive manual review.

### What Problem It Solves

- **Lack of content visibility:** Organisations cannot see what sensitive data lives in their document repositories without reading every file.
- **Classification inconsistency:** Manual tagging by employees is unreliable and incomplete.
- **Privacy risk blindspot:** Regulated data (PII, financial credentials, health data) may exist in locations with inappropriate access controls.
- **Governance reporting gap:** Compliance teams have no automated way to produce a current inventory of high-risk documents.

### Who It Is For

This PoC was designed to demonstrate a practical solution to a privacy governance challenge. The target audience for a production version of this system includes:

- **Privacy / Data Governance teams** — who need a continuous inventory of where sensitive data lives
- **Information Security teams** — who need to identify high-risk documents before a breach event
- **Compliance teams** — who need audit-ready evidence of document classification and risk controls
- **IT / SharePoint administrators** — who need tooling to enforce information governance policies at scale

### What the PoC Demonstrates

1. Automated document ingestion from a simulated multi-site SharePoint environment
2. AI-powered classification of documents into 10 functional business categories
3. Three-tier sensitivity scoring (Low / Moderate / High) with PII detection
4. A consistent 1–10 risk score for each document based on sensitivity, content type, and metadata
5. A web-based dashboard displaying classification results, risk distribution, and PII inventory
6. Ability to upload arbitrary documents for on-demand classification and inline sensitive-content highlighting
7. RAG (retrieval-augmented generation) context injection to improve classification accuracy
8. Rule-based pre-analysis and post-validation to prevent LLM hallucination on well-defined PII signals

### What Is Intentionally Simplified

Because this is a demonstration system built for a proof-of-concept, the following are intentionally simplified:

| Simplified Area | Production Equivalent |
|---|---|
| Local flat-file folders simulating SharePoint sites | Real Microsoft Graph API + SharePoint REST API integration |
| Fake/synthetic documents as test data | Real enterprise document libraries |
| Heuristic risk scoring formula | ML-trained risk model calibrated to real data |
| No enterprise authentication | Azure AD / Entra ID SSO integration |
| No permission-based access modelling | Microsoft Graph permission API exposing who-can-read-what |
| In-memory rate limiting | Distributed Redis-backed rate limiter |
| Single-instance Flask server | Enterprise WSGI server (gunicorn + nginx) with horizontal scaling |
| JSON file persistence | Relational database (PostgreSQL / Azure SQL) |

---

## 2. Solution Overview & Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         WEB BROWSER (User)                              │
│          Dashboard · Browse · Upload · Scan · Report                    │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │  HTTP / REST JSON
┌──────────────────────────────▼──────────────────────────────────────────┐
│                     FLASK APPLICATION LAYER                              │
│                        app_unified.py                                   │
│   Routes · Rate Limiting · Security Headers · File Upload Handler       │
└──────┬─────────────────┬──────────────────┬──────────────────┬──────────┘
       │                 │                  │                  │
┌──────▼──────┐  ┌───────▼──────┐  ┌───────▼──────┐  ┌───────▼──────────┐
│  CONTENT    │  │    RAG       │  │  AI CLASSI-  │  │   SHAREPOINT    │
│  EXTRACTOR  │  │   ENGINE     │  │    FIER      │  │    SCANNER      │
│             │  │              │  │              │  │                 │
│ .txt .docx  │  │ Embeddings   │  │ Pre-Analysis │  │ Site Discovery  │
│ .pdf parser │  │ Similarity   │  │ Gemini API   │  │ File Enumerat.  │
│             │  │ Knowledge    │  │ Ollama Fallb.│  │ Batch Process.  │
│             │  │ Base Lookup  │  │ Post-Validat.│  │                 │
└──────┬──────┘  └───────┬──────┘  └──────┬───────┘  └────────────────┘
       │                 │                 │
       └─────────────────▼─────────────────┘
                         │  Classification Result
              ┌──────────▼──────────┐
              │   STORAGE LAYER     │
              │                     │
              │  /uploads/          │
              │  /reports/          │
              │  human_verif*.json  │
              │  risk_report*.json  │
              └─────────────────────┘
                         │
              ┌──────────▼──────────┐
              │  EXTERNAL SERVICES  │
              │                     │
              │  Google Gemini API  │
              │  (primary LLM)      │
              │                     │
              │  Ollama (local LLM) │
              │  (quota fallback)   │
              └─────────────────────┘
```

### Component Descriptions

#### Ingestion Layer — `core/content_extractor.py`

Responsible for reading raw file bytes and returning clean plain text. Supports `.txt` (direct read), `.docx` (via `python-docx`), and `.pdf` (via `PyPDF2`). Enforces a 5 MB file-size limit. **Critically, extracted text is never written to disk** — it is passed in-memory to the next stage and discarded after classification.

#### SharePoint Scanner — `core/sharepoint_scanner.py`

Simulates a SharePoint environment by mapping named "sites" (e.g., Finance Team, HR Department) to local subdirectories under `demo_sharepoint/`. Provides file enumeration, batch scanning coordination, and site-level summary aggregation. In a production system, this component would be replaced by Microsoft Graph API calls against real SharePoint libraries.

#### RAG Engine — `core/rag_engine.py`

Implements a lightweight retrieval-augmented generation layer. On startup it loads `knowledge_base.json` — a curated set of functional group descriptions, keywords, and example document types. It embeds the knowledge base using `sentence-transformers` (model: `all-MiniLM-L6-v2`). When a document is ingested, the first 2,000 characters are embedded and cosine similarity is used to retrieve the top-*k* matching functional groups. This context is passed to the classifier to ground its decisions.

#### AI Classifier — `core/ai_classifier.py`

The core intelligence layer. Classification is a three-stage pipeline:

1. **Pre-analysis** — deterministic regex scans (18 PII patterns) and domain keyword scoring before any LLM call
2. **LLM inference** — structured prompt sent to Google Gemini (`gemini-2.0-flash`), with pre-analysis signals injected as ground truth
3. **Post-validation** — rule-based corrections applied to the LLM output to prevent hallucination on clear-cut cases

If Gemini quota is exhausted, the classifier automatically retries against a local Ollama instance (default model: `llama3.2`) using the identical prompt. If Ollama is also unavailable, it falls back to a pure keyword-based classifier.

#### Flask Application — `app_unified.py`

Single-file Flask application exposing all UI views (Jinja2 templates) and REST API endpoints. Handles file upload, classification requests, site scan orchestration, report export, and human verification recording. Includes per-route rate limiting and HTTP security headers on every response.

#### Dashboard & Frontend — `templates/`

Server-rendered HTML templates using Jinja2. Client-side interactivity is implemented in vanilla JavaScript. UI components use Bootstrap for layout. The dashboard uses Chart.js for the sensitivity distribution chart and the risk score histogram. The browse and upload pages include an inline document viewer with colour-coded PII highlighting.

### Data Flow

```
User uploads file  / selects document to classify
         │
         ▼
content_extractor.py ── reads file ──► plain text (in memory)
         │
         ├──► rag_engine.retrieve(text, top_k=3)
         │         │ embeds first 2000 chars
         │         │ cosine similarity vs knowledge base
         │         └──► top-3 functional group hints
         │
         └──► ai_classifier.classify(text, filename)
                   │
                   ├── 1. _pre_analyze()
                   │       18 × regex PII scanners
                   │       domain keyword scoring (9 groups)
                   │       filename boost heuristics
                   │       → pre_analysis dict
                   │
                   ├── 2. _build_prompt()
                   │       inject pre_analysis cheat-sheet
                   │       smart content window (first 10k + last 2k chars)
                   │       RAG group hints included
                   │       → structured prompt string
                   │
                   ├── 3. Gemini API call  (or Ollama → keyword fallback)
                   │       → raw JSON response text
                   │
                   ├── 4. _parse_response()
                   │       extract JSON from response
                   │       validate required fields
                   │       → result dict
                   │
                   └── 5. _post_validate()
                           force High sensitivity if hard PII found
                           merge any missed PII types
                           override weak group if score gap ≥ 4
                           bump risk_score by PII count
                           → final classification dict
         │
         ▼
Flask route returns JSON to browser
Browser renders result (sensitivity badge, PII list, risk score, highlighted content)
```

---

## 3. Technology Stack

### Backend

| Component | Technology | Version | Notes |
|---|---|---|---|
| Language | Python | 3.11+ | Standard CPython |
| Web framework | Flask | 2.3.3 | Lightweight WSGI framework |
| Template engine | Jinja2 | 3.1.2 | Server-side HTML rendering |
| WSGI toolkit | Werkzeug | 2.3.7 | Routing, file handling, `secure_filename` |
| Environment config | python-dotenv | 1.0.0 | `.env` file loading |
| Rate limiting | flask-limiter | 3.5.0 | Per-route request throttling |
| Document parsing — Word | python-docx | 0.8.11 | `.docx` extraction |
| Document parsing — PDF | PyPDF2 | 3.0.1 | `.pdf` extraction |
| Document parsing — Excel | openpyxl | 3.1.2 | `.xlsx` support (future use) |
| Document parsing — PPT | python-pptx | 0.6.21 | `.pptx` support (future use) |
| HTTP requests | requests | 2.31.0 | Outbound HTTP (Ollama calls) |
| Database | SQLite3 (stdlib) | 3.x | Built-in Python; used for structured persistence if needed |

### AI / LLM

| Component | Technology | Notes |
|---|---|---|
| Primary LLM | Google Gemini | `gemini-2.0-flash` (configurable via `GEMINI_MODEL` env var) |
| Gemini SDK | google-genai | `genai.Client` with `models.generate_content()` |
| Temperature | 0.1 (Ollama); Gemini default | Low temperature enforces deterministic, consistent classification |
| Max output tokens | ~800 (Ollama); Gemini default | Sufficient for structured JSON classification response |
| Context window used | Up to 12,000 chars | First 10,000 + last 2,000 chars of document for large files |
| Prompt strategy | Structured JSON with injected pre-analysis ground truth | See Section 4 |
| Quota fallback | Ollama (local LLM) | Same prompt, same JSON output schema |
| Fallback model | `llama3.2` (configurable via `OLLAMA_MODEL`) | ~2 GB, runs on CPU |
| Last-resort fallback | Keyword classifier | Pure regex + domain scoring, no LLM |

#### Prompt Engineering Strategy

The prompt is a single structured string composed of five sections:

1. **Role declaration** — "You are a document classification expert…"
2. **Pre-analysis cheat-sheet block** — deterministic regex findings injected verbatim, labelled "treat as ground truth"
3. **Classification rules** — definitions of all 10 functional groups with disambiguation rules and a strict priority order
4. **Sensitivity definitions** — criteria for Low / Moderate / High with exhaustive examples
5. **Response schema** — exact JSON format the model must return (see Section 4)

This design intentionally prevents the LLM from overriding objectively detected PII and constrains its creative latitude to the ambiguous middle ground (group selection, reasoning text).

### RAG

| Component | Technology | Notes |
|---|---|---|
| Embedding model | `all-MiniLM-L6-v2` | Via `sentence-transformers` 2.2.2 |
| Fallback embeddings | TF-IDF | Via `scikit-learn` if sentence-transformers unavailable |
| Vector store | In-memory dict | Embeddings held in RAM; no external vector DB required |
| Similarity metric | Cosine similarity | Numpy dot-product on normalised vectors |
| Knowledge base | `knowledge_base.json` | 10 groups × descriptions + keywords + document type examples |
| Chunking strategy | First 2,000 chars for RAG retrieval | Full document used for classifier prompt (up to 12k chars) |

### Frontend

| Component | Technology | Notes |
|---|---|---|
| Markup | HTML5 | Server-rendered via Jinja2 |
| CSS framework | Bootstrap 5 | Grid, components, utility classes |
| Custom CSS | `templates/brand-styles.css` | Branding overrides, PII highlight colours, drawer animations |
| Charting | Chart.js | Sensitivity distribution doughnut, risk histogram, group bar chart |
| Icons | Font Awesome 6 | Used throughout nav, cards, badges |
| JavaScript | Vanilla ES6+ | No frontend build step; no framework (React/Vue) |
| PII highlighting | Custom JS engine | Regex-based 18-pattern scanner in browser; colour-coded `<mark>` tags with hover tooltips |

### Storage

| Artefact | Location | Format | Retention |
|---|---|---|---|
| Uploaded documents | `/uploads/` | Original file (timestamped filename) | Persisted until manually deleted |
| Risk reports (export) | `/reports/risk_report_<timestamp>.json` | JSON | Persisted |
| Human verification records | `/reports/human_verifications.json` | JSON array, append-only | Persisted |
| Embeddings | In-memory dict (`rag_engine.embeddings`) | NumPy array | Recomputed on each server start |
| Classification results | In-memory during request | Python dict | Not persisted — returned to browser only |
| Extracted document text | In-memory during request | String | Never written to disk |

---

## 4. AI Classification Design

### The 10 Functional Groups

| # | Group Name | Scope | High-Risk Indicators |
|---|---|---|---|
| 1 | **HR** | Employee lifecycle, workforce management | SSNs, employee IDs, salary, performance reviews, disciplinary records |
| 2 | **Finance and Accounting** | Financial reporting, accounting, tax, transactions | Account numbers, GL codes, EBITDA, routing numbers, invoices |
| 3 | **Legal + Compliance** | Contracts, regulatory filings, litigation | "Whereas", indemnification, jurisdiction, GDPR/SOX/HIPAA citations |
| 4 | **Customer / Client Documentation** | Client relationship management, generic engagement deliverables with no dominant functional topic | Client names, account IDs, engagement references |
| 5 | **Sales & Business Development** | Revenue generation, deal tracking, pipeline | Deal stage, win probability, CRM data, pricing models |
| 6 | **Marketing & Communications** | External messaging, brand communication | Campaign KPIs, brand voice, press releases |
| 7 | **IT & Systems** | Technology infrastructure, cloud, system operations, credentials | IP addresses, API keys, server configs, VPN, AWS/Azure/GCP, encryption keys |
| 8 | **Product Development / R&D** | Research, product strategy, engineering | Roadmaps, sprint backlogs, user stories, prototype specs |
| 9 | **Operations and Internal Documentation** | Internal processes, SOPs, meeting minutes | Workflow descriptions, SOPs, operational KPIs |
| 10 | **Outliers / Others** | Fallback for genuinely unclassifiable documents | Files with no discernible business context |

> **Critical design note:** "Customer / Client Documentation" is deliberately narrow. Consulting or advisory documents are classified by their *subject matter domain* (IT, HR, Finance, etc.), not by the fact they were written for a client. The prompt enforces a strict priority order (Legal → HR → Finance → IT → Product → Sales → Marketing → Operations → Customer/Client → Outliers) that prevents the lazy catch-all assignment that many classification systems produce.

### Classification Pipeline

```
        Raw document text
               │
   ┌───────────▼────────────┐
   │  1. _pre_analyze()     │  ← Runs BEFORE any LLM call
   │                        │
   │  18 × regex PII scans  │    SSN, Credit Card, Routing No., SWIFT,
   │  Domain keyword score  │    Bank Acct, IBAN, Wire Transfer,
   │  Filename boost (×2)   │    Password, API Key, Secret Key,
   │                        │    Email, Phone, Employee ID, DOB,
   │                        │    Dollar Amount, Salary, Medical, Regulatory
   └───────────┬────────────┘
               │ pre_analysis dict
   ┌───────────▼────────────┐
   │  2. _build_prompt()    │
   │                        │
   │  Inject pre_analysis   │
   │  as "ground truth"     │
   │  block at prompt top   │
   │  + full classification │
   │  rules + schema        │
   └───────────┬────────────┘
               │ prompt string (up to ~15k chars)
   ┌───────────▼────────────┐
   │  3. Gemini API call    │  (or Ollama → keyword fallback)
   └───────────┬────────────┘
               │ raw response text
   ┌───────────▼────────────┐
   │  4. _parse_response()  │
   │                        │
   │  Extract JSON block    │
   │  (handles markdown     │
   │   ```json fences)      │
   │  Validate required     │
   │  fields; fill defaults │
   └───────────┬────────────┘
               │ result dict
   ┌───────────▼────────────┐
   │  5. _post_validate()   │  ← Rule-based corrections
   │                        │
   │  Force High if hard    │    If has_high_pii → sensitivity=High, risk≥7.5
   │  PII detected          │
   │  Merge missed PII      │    Add any PII types the LLM missed
   │  Override weak groups  │    If keyword score gap ≥4 and LLM picked
   │  Bump risk by PII ct   │    a weak group → override to domain winner
   └───────────┬────────────┘
               │ final classification dict
```

### Single-Label Enforcement

The prompt explicitly instructs the model to classify into **exactly one** functional group. The prompt contains:

> *"Classify it into ONE of the 10 functional groups below"*

The JSON response schema `functional_group` is a single string, not an array. The post-validator enforces this by using only the top domain-score winner when overriding the LLM.

### Sensitivity Classification Rules

Three tiers, defined in the prompt with exhaustive examples:

**High** — document contains *any* of:
- Personal identifiers (SSN, employee IDs with personal data, passport, driver's licence)
- Financial credentials (bank account, credit card, routing number, wire transfer details)
- Contracts with legal liability (indemnification, settlement amounts, litigation exposure)
- Protected health information (PHI, patient IDs, HIPAA-covered data)
- Security credentials (API keys, passwords, encryption keys, connection strings)
- Regulated data (GDPR personal data, PCI-DSS payment data)
- Executive compensation, board materials, M&A strategy

**Moderate** — document contains internal business information without hard PII:
- Internal business plans or confidential strategy
- Client contact information (names, emails, phone numbers only)
- Pricing models, discount structures
- Budget forecasts (not account numbers)
- Performance reviews (without personal identifiers)

**Low** — document contains:
- Public-facing content or press releases
- Generic SOPs with no sensitive examples
- Published or non-confidential materials

### Confidence Scoring

Confidence is a float on `[0.0, 1.0]` returned by the LLM. The pre-analysis and post-validation layers do not modify the confidence value — it reflects the LLM's self-reported certainty. A confidence of `0.3` is assigned automatically to all keyword-fallback results to signal that no LLM was used.

### JSON Response Schema

The model is required to return a strict JSON object:

```json
{
  "functional_group": "HR",
  "sensitivity_level": "High",
  "confidence": 0.92,
  "risk_score": 8.5,
  "pii_detected": ["SSN", "Employee ID", "Salary/Compensation"],
  "reasoning": "Document contains payroll records with SSNs and salary figures...",
  "document_summary": "Quarterly payroll reconciliation report for Q1 2026...",
  "confidential_findings": [
    "Contains 47 Social Security Numbers",
    "Salary data for all employees present"
  ],
  "classification_status": "success"
}
```

The `_parse_response()` method extracts this from the model's output (stripping any markdown code fences), then fills safe defaults for missing fields before returning.

### Guardrails Against Hallucination

| Guardrail | Mechanism |
|---|---|
| PII cannot be unmade | `_post_validate()` forces `sensitivity=High` and `risk≥7.5` whenever `_pre_analyze()` detected hard PII, regardless of what the LLM returned |
| Weak group override | When keyword domain score for a group leads the LLM's chosen group by ≥4 points, and the LLM picked a "catch-all" group, the post-validator overrides with the keyword winner |
| Missing PII types | Any PII type found by regex but absent from the LLM's `pii_detected` list is merged in by the post-validator |
| Temperature | LLM is called at low temperature (0.1 for Ollama) to reduce creative variance |
| Deterministic ground truth | Pre-analysis signals are labelled "deterministic regex results — treat as ground truth" in the prompt, explicitly instructing the model not to contradict them |
| Risk score floor | Post-validator ensures `risk_score ≥ 6.0` when any PII is found, and `≥ 8.0` when 3+ PII types are found |

### Handling Ambiguous Documents

- The prompt provides a full **disambiguation rules** section covering 20+ common ambiguous patterns (e.g., consulting report with IT content → IT & Systems; mixed-topic client deliverable → Customer/Client)
- A **priority order** (1–10) is enforced: regulated content overrides group assignment at the top; Outliers/Others is a last resort
- The `_pre_analyze()` keyword scoring provides a quantitative signal that the post-validator can use to override purely linguistic LLM choices

### Why AI Instead of Pure Keyword Rules

A pure keyword classifier struggles with:
- **Synonymy** — "compensation plan" and "pay strategy" mean the same thing; a keyword list cannot enumerate all variations
- **Context-dependence** — the word "budget" appears in Finance documents, Marketing campaign briefs, and IT infrastructure plans; only context resolves the ambiguity
- **Document tone and structure** — a legal letter is recognisably different from a finance spreadsheet even when they share vocabulary
- **Composite documents** — a consulting report covering IT architecture for a financial services client contains IT and Finance keywords; rule-based systems cannot resolve priority

The LLM provides natural language understanding that resolves these cases. The pre-analysis and post-validation layers add deterministic correctness for well-defined PII signals, giving the best of both approaches.

### Limitations of Generative Classification

- LLMs are probabilistic; the same document may receive slightly different classifications across runs (mitigated by low temperature and post-validation)
- Gemini's classification decisions are not fully explainable — the reasoning field is the model's self-reported rationale, not a verifiable audit trail
- Classification accuracy has not been formally benchmarked (no labelled ground-truth dataset)
- The model may be influenced by document language/style in ways that introduce bias

---

## 5. RAG Design

### What Is Retrieved

For each document, the RAG engine retrieves the **top-3 most semantically similar functional group descriptions** from the knowledge base. Each retrieved result includes:
- Group name and description
- Keywords associated with the group
- Example document types
- Similarity score (0.0–1.0)
- A context string summarising the match

### How Embeddings Are Generated

On application startup, `rag_engine.py` embeds all 10 functional group descriptions using `sentence-transformers` model `all-MiniLM-L6-v2`. These embeddings are stored in a Python dict in RAM.

At classification time, the first 2,000 characters of the incoming document are embedded using the same model. This length is chosen to capture the document header, title, author, and key opening content — which are typically the most discriminative signals.

Fallback chain:
1. `sentence-transformers` (semantic embedding, cosine similarity) — preferred
2. `TF-IDF` + cosine similarity — if sentence-transformers is not installed
3. Keyword overlap counting — if sklearn is also unavailable

### How Context Is Injected into the Prompt

The RAG results are passed to `_build_prompt()` alongside the document text and pre-analysis signals. The top-*k* group matches and their similarity scores are included in the prompt as supporting signal, helping the LLM understand which categories are semantically close to the document's content.

### Chunking Strategy

| Stage | Characters Used | Rationale |
|---|---|---|
| RAG retrieval | First 2,000 | Header/title/opening content is most discriminative |
| LLM prompt | First 10,000 + last 2,000 | Captures document introduction and conclusion; middle omitted with a clear label for very long documents |

### Similarity Search Method

Cosine similarity between the document embedding vector and each group embedding vector. Implemented via `numpy` dot product on L2-normalised vectors:

```python
similarity = np.dot(doc_embedding, group_embedding)  # on unit vectors
```

### Why RAG Improves Classification Consistency

Without RAG, the LLM sees only the raw document and the group definitions in the system prompt. With RAG, it also sees a ranked list of which groups are *semantically closest* to the actual document text — reinforcing the correct classification choice and providing a quantitative similarity signal that reduces ambiguous group selection. Empirically, RAG-augmented classification produces fewer "Customer / Client Documentation" catch-all misclassifications on specialist documents.

---

## 6. Risk Scoring Framework

### Overview

Each document receives a single continuous risk score on a 1.0–10.0 scale (rounded to 1 decimal place). The score is used to drive the dashboard's risk tier visualisation and the high-risk document filter.

A document is flagged **High Risk** if:
- `risk_score >= 7.0`, OR
- `sensitivity_level == "High"`, OR
- `len(pii_detected) > 0`

### Risk Score Sources

There are two code paths that produce a risk score:

**Path 1 — AI-generated score (primary)**

When the Gemini or Ollama LLM is used, the model returns a `risk_score` field in its JSON response. This value is the LLM's holistic assessment of document risk given all the content signals it observed.

The post-validator then applies floors:
```
if pii_count >= 3:  risk_score = max(risk_score, 8.0)
if pii_count >= 1:  risk_score = max(risk_score, 6.0)
if has_high_pii:    risk_score = max(risk_score, 7.5)
```

**Path 2 — Heuristic score (keyword fallback & Meridian demo path)**

When no LLM is available, the risk score is derived from a base risk per functional group/sensitivity combination, with a small deterministic jitter applied:

```python
seed   = int(hashlib.md5(filename.encode()).hexdigest()[:6], 16)
jitter = (seed % 20 - 10) / 10.0      # range: -1.0 to +1.0
raw    = min(10.0, max(1.0, base_risk + jitter))
score  = round(raw * 10) / 10
```

The MD5-based jitter ensures that the same filename always produces the same score (deterministic), while adding enough variance to make the demo dataset visually realistic.

### Functional Group Base Risk Values

| Functional Group | Base Risk | Rationale |
|---|---|---|
| HR (payroll/SSNs) | 8.5 | Highest — contains personal identifiers and compensation data |
| Finance (banking/routing) | 8.0 | Account numbers and financial credentials |
| IT Systems (credentials/infra) | 6.9–8.5 | Ranges by sub-type; credential files score highest |
| Legal + Compliance | 7.5–8.0 | Binding legal obligations and liability exposure |
| Customer / Client | 5.8 | Business-sensitive but typically no hard PII |
| Sales & Business Development | 5.0 | Commercial sensitivity, competitive information |
| Product Development / R&D | 4.5 | IP-sensitive but usually no regulated data |
| Operations & Internal | 3.5 | Process documentation, low regulated-data exposure |
| Marketing & Communications | 3.0 | Typically public-facing content |
| Outliers / Others | 2.0 | Unknown content; residual risk |

### Weight Assumptions

These base risk values are informed by the types of regulated data typically present in each group:
- Groups containing regulated personal data (PII, PHI) score 7.5–9.0
- Groups containing financial account data score 7.5–8.5
- Groups containing business-confidential but not regulated data score 5.0–7.0
- Groups containing primarily operational or public content score 2.0–4.5

### Limitations of the Risk Scoring Approach

- **Heuristic, not trained** — base risk values are manually assigned, not derived from a labelled training set or statistical model
- **No access exposure modelling** — risk does not account for how many users have read access to the document (a critical factor in real privacy risk)
- **File age not incorporated** — stale documents sitting in shared drives represent elevated risk but the current model does not penalise age
- **Single-document scope** — the score reflects per-document content risk only; it does not account for aggregate risk (e.g., 50 high-risk HR documents in an insecure folder)
- **No calibration validation** — the score has not been tested against expert-labelled risk assessments; precision and recall at various thresholds are unknown

---

## 7. Data Model & Storage

### Overview

The PoC uses a flat-file storage approach rather than a relational database. Classification results are ephemeral (returned to the browser in the API response but not persisted to disk). Only three types of data are persisted:

| File | Location | Written By | Contents |
|---|---|---|---|
| Uploaded documents | `/uploads/<timestamp>_<filename>` | `api_upload()` route | Original file binary |
| Risk report exports | `/reports/risk_report_<timestamp>.json` | `api_export_report()` route | Full scan results snapshot |
| Human verifications | `/reports/human_verifications.json` | `api_verify_document()` route | Reviewer overrides/confirmations |

### Classification Result Structure (In-Memory / API Response)

The following represents the complete structure returned by the `/api/classify` and `/api/upload` endpoints, and passed between internal components:

```json
{
  "status": "success",
  "file": "employee_payroll_q1_2026.txt",
  "file_path": "uploads/20260227_143022_employee_payroll_q1_2026.txt",

  "classification": {
    "functional_group":      "HR",
    "sensitivity_level":     "High",
    "confidence":            0.94,
    "risk_score":            9.1,
    "pii_detected":          ["SSN", "Employee ID", "Salary/Compensation", "Bank Account"],
    "reasoning":             "Document is a payroll reconciliation containing...",
    "document_summary":      "Q1 2026 payroll reconciliation for all employees...",
    "confidential_findings": [
      "Contains 38 Social Security Numbers",
      "Full salary and bank account data for every listed employee"
    ],
    "classification_status": "success",
    "model_used":            "gemini-2.0-flash"
  },

  "risk_assessment": {
    "risk_score":    9.1,
    "has_pii":       true,
    "sensitivity":   "High",
    "is_high_risk":  true
  },

  "rag_context": [
    {
      "group_id":         1,
      "name":             "HR & Personnel Management",
      "similarity_score": 0.87,
      "matched_keywords": ["payroll", "employee", "SSN", "salary"],
      "context":          "Strong match: HR group description aligns with payroll..."
    }
  ],

  "text_preview": "PAYROLL RECONCILIATION REPORT — Q1 2026\nEmployee: John Smith\nSSN: 123-45-6789..."
}
```

### Human Verification Record Structure

```json
{
  "document_id": "employee_payroll_q1_2026.txt",
  "original_classification": "HR",
  "verified_classification":  "HR",
  "reviewer_notes":           "Confirmed — payroll file with full SSN exposure",
  "is_confirmed":             true,
  "reviewed_at":              "2026-02-27T14:35:00Z"
}
```

### Fields Intentionally NOT Stored

| Field | Why Not Stored |
|---|---|
| Extracted document text | Privacy by design — raw content is never written to disk; processed in memory only |
| API keys used | Only stored in `.env` / environment variables; never logged or persisted |
| User identity / IP address | No authentication system; no session data stored |
| Intermediate LLM responses | Discarded after parsing |
| Embedding vectors | Recomputed in memory at startup; not serialised |

### Normalization Decisions

The current flat-file approach was chosen deliberately for the PoC to reduce infrastructure dependencies. In a production system:

- `classification_results` would be a SQL table indexed by `document_id` and `scan_id`
- `scan_logs` would record each scan run with timestamp, site, document count, and success/failure counts
- `documents` would store metadata (name, size, path, dates) separately from `classification_results` to support re-classification without re-ingestion
- `risk_scores` would be versioned to support historical comparison

---

## 8. Security & Privacy Considerations

### No Raw Content Stored

The most significant privacy design decision in the system is that **document text is never written to disk**. The content extraction pipeline reads the file, extracts text as a Python string, passes it in-memory through the RAG engine and classifier, and then discards it. The only file that persists is the original uploaded binary (in `/uploads/`) which allows re-retrieval for the inline document viewer.

### Temporary Processing Only

Classification of scanned documents (in `demo_sharepoint/`) does not create any artefact. The files are read, classified, and the result returned to the browser. Nothing is appended to a database or log file unless the user explicitly exports a report or submits a human verification.

### API Key Handling

- All secrets are stored in `.env` (which is gitignored) and loaded via `python-dotenv`
- The Flask application reads `GEMINI_API_KEY`, `GEMINI_API_KEY_2`, and `FLASK_SECRET_KEY` from environment variables at startup
- A backup Gemini key (`GEMINI_API_KEY_2`) is supported at the infrastructure level
- No API key is ever sent to the browser, logged to a file, or included in any API response
- When deploying to a hosted platform, secrets must be set as platform environment variables — the `.env` file should not be deployed

### Flask Secret Key

A strong 256-bit secret key is required for Flask sessions and CSRF protection. It is loaded from `FLASK_SECRET_KEY` in `.env`. If absent, the application generates a random key at startup (with a warning) — acceptable for development, not for production since sessions will not persist across restarts.

### Rate Limiting

Per-route rate limits prevent API abuse from exhausting external service quotas:

| Endpoint | Per-Hour Limit | Per-Minute Limit |
|---|---|---|
| `POST /api/classify` | 30 | 5 |
| `POST /api/upload` | 20 | 5 |
| `POST /api/scan/site` | 10 | 3 |

Exceeded limits return a structured JSON `429` response with a `retry_after` field.

### HTTP Security Headers

The following headers are set on every HTTP response:

| Header | Value | Purpose |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | Prevent MIME-type sniffing |
| `X-Frame-Options` | `SAMEORIGIN` | Prevent clickjacking |
| `X-XSS-Protection` | `1; mode=block` | Legacy XSS filter (legacy browsers) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limit referrer leakage |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=()` | Disable unnecessary browser APIs |

`Strict-Transport-Security` is present but commented out — it should be enabled once HTTPS is confirmed on the hosting platform.

### Logging Controls

The application uses Python's `logging` module at `INFO` level. Logs are written to stdout only (not to file). Log statements record classification events, errors, and API calls but never include document content or API key values.

### File Deletion Policy

Uploaded files are currently retained in `/uploads/` indefinitely. In a production deployment, a scheduled cleanup job should remove uploads older than a defined retention window (e.g., 24 hours). The demo SharePoint files in `/demo_sharepoint/` are static test data and are never modified by the application.

---

## 9. Limitations of the Prototype

The following limitations are acknowledged by design. They represent the gap between a production-grade system and the current PoC.

| Limitation | Impact | Production Resolution |
|---|---|---|
| **No real SharePoint integration** | Documents are read from local folders, not live SharePoint libraries. Cannot scan real organisational content. | Microsoft Graph API + SharePoint REST API |
| **No enterprise authentication** | Any user who can reach the app URL can access all documents and results. No identity verification. | Azure AD / Entra ID OAuth 2.0 |
| **No permission-based access modelling** | Risk scoring does not account for who can see the document. A High sensitivity document accessible to 500 users is not scored higher than one accessible to 2. | Microsoft Graph permissions API; incorporate user scope into risk formula |
| **No role-based access control** | All users see identical views. Reviewers, admins, and read-only users are not differentiated. | RBAC tied to AD group membership |
| **AI classification variability** | LLM outputs are probabilistic. Identical documents may receive marginally different classifications across runs. Temperature and post-validation reduce but do not eliminate this. | Formal validation dataset; fine-tuned classification model |
| **No formal model validation** | Classification accuracy (precision, recall, F1) has not been measured against a labelled ground-truth dataset. Performance claims cannot be substantiated. | Labelled benchmark dataset; cross-validation against expert opinions |
| **Heuristic risk scoring** | Base risk values are manually assigned. The formula has not been calibrated against real risk incidents or expert assessments. | ML-trained risk model; actuarial calibration |
| **Single-instance rate limiting** | `flask-limiter` with `memory://` storage does not share state across multiple server processes or workers. | Redis-backed limiter (`storage_uri='redis://'`) |
| **No audit trail** | There is no immutable record of who accessed which document, when, or what was classified. | Append-only audit log stored in a database with tamper detection |
| **No real-time scanning** | Documents are scanned on demand; there is no background watcher that triggers classification when new documents are added. | Microsoft Graph webhook subscriptions (change notifications) |
| **Supported file types limited** | Only `.txt`, `.docx`, and `.pdf` are processed. `.xlsx`, `.pptx`, emails, and SharePoint pages are not ingested. | Extended parser library; Microsoft Graph content extraction API |
| **5 MB file size limit** | Large documents (e.g., multi-hundred-page PDFs) are truncated or rejected. | Chunked processing pipeline; streaming extraction |

---

## 10. Future Enhancements

The following enhancements would be required to move from a demonstration PoC to a production-grade governance system.

### Tier 1 — Core Infrastructure (Required for Production)

**Microsoft Graph Integration**  
Replace simulated SharePoint folders with real Microsoft Graph API calls. This enables live document discovery, metadata retrieval (author, last modified, permissions), and change-event subscriptions so new documents are automatically classified when uploaded.

**Azure AD / Entra ID Authentication**  
Require login via Microsoft SSO before accessing the application. This enables identity-aware risk scoring (who uploaded it, who can access it) and role-based dashboards where compliance officers see different views from end users.

**Real Permission Exposure Modelling**  
Query the Microsoft Graph permissions API to identify who has read access to each document. Incorporate access scope into the risk formula: a High sensitivity document accessible to an entire organisation scores significantly higher than the same document in a tightly controlled private library.

**Relational Database (PostgreSQL / Azure SQL)**  
Replace JSON flat-file storage with a proper relational schema. This enables historical analysis, trend reporting (risk improving or worsening over time), re-classification tracking, and audit-quality record keeping.

### Tier 2 — AI & Classification Quality

**Model Fine-Tuning**  
Fine-tune a classification model on organisational document samples with human-verified labels. This would eliminate dependence on a large general-purpose LLM for routine classification tasks and produce more consistent, faster results.

**Evaluation Metrics**  
Build a labelled benchmark dataset (500–1,000 documents with expert-assigned functional groups and sensitivity labels). Measure precision, recall, F1, and confusion matrix at each release to track classification regression.

**Confidence Calibration**  
The LLM's self-reported confidence score is not calibrated (a 0.9 confidence does not mean 90% accuracy). Apply isotonic regression or Platt scaling to map raw confidence scores to calibrated probabilities.

**Multi-Label Classification**  
Allow a document to carry a primary classification and one or more secondary classifications for documents that meaningfully span two domains (e.g., an employment contract that is both HR and Legal).

### Tier 3 — Governance & Reporting

**Role-Based Dashboards**  
Separate views for: Privacy Officer (PII inventory across all sites), CISO (high-risk document exposure), Site Owner (documents they are responsible for), End User (their own uploaded documents only).

**Automated Remediation Suggestions**  
When a high-risk document is identified in an inappropriately permissive location, suggest concrete actions: restrict access, apply a sensitivity label, schedule a review, or flag for deletion.

**Retention Policy Enforcement**  
Cross-reference document age against the organisation's data retention schedule. Flag documents that should have been deleted under the policy.

**Integration with Microsoft Purview**  
Surface classification results as Microsoft Information Protection (MIP) sensitivity labels, making classifications visible and enforceable within the Microsoft 365 ecosystem (Outlook, Teams, SharePoint natively).

**Power BI / Reporting API**  
Expose classification data via a structured API that feeds into Power BI dashboards for executive-level privacy risk visibility.

### Tier 4 — Scale & Reliability

**Background Processing Queue**  
Replace synchronous in-request classification with an async job queue (Celery + Redis). This allows bulk site scans to run in the background without browser timeout, and supports retry logic for failed classifications.

**Caching Layer**  
Cache classification results by document content hash so unchanged documents are not re-classified on every scan. This dramatically reduces API cost and latency in large repositories.

**Horizontal Scaling**  
Deploy behind a load balancer with multiple Flask workers (gunicorn) and a shared Redis instance for rate limiting and job state.

**LLM Cost Benchmarking**  
As document volume scales, track Gemini API token consumption per scan. Evaluate whether a fine-tuned smaller model (served via Ollama or Azure AI) delivers acceptable accuracy at lower cost per document.

---

*End of System Documentation*
