# AI Document Classification System — Technical Reference
## Engineering Deep-Dive: Architecture, AI Pipeline, Risk Scoring & Rebuild Guide

**Version:** 1.0  
**Date:** February 2026  
**Audience:** Engineering teams, technical reviewers, PoC replicators  

---

## Table of Contents

1. [System Architecture Breakdown](#1-system-architecture-breakdown)
2. [AI Pipeline — Detailed Implementation](#2-ai-pipeline--detailed-implementation)
3. [RAG Design](#3-rag-design)
4. [Risk Scoring Logic](#4-risk-scoring-logic)
5. [Database / Storage Design](#5-database--storage-design)
6. [Security Design](#6-security-design)
7. [Rebuild Instructions](#7-rebuild-instructions)

---

## 1. System Architecture Breakdown

### Layer Overview

The system is composed of five distinct layers, each with a single responsibility. All layers run within a single Python process — there are no microservices, message queues, or external infrastructure dependencies beyond the Gemini API.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — PRESENTATION (Browser)                                           │
│  templates/*.html  •  brand-styles.css  •  Vanilla JS  •  Chart.js          │
│  Bootstrap 5  •  Font Awesome 6                                             │
└──────────────────────────────┬──────────────────────────────────────────────┘
                     HTTP/REST │ JSON API  +  Jinja2 server-render
┌──────────────────────────────▼──────────────────────────────────────────────┐
│  LAYER 2 — APPLICATION (Flask)                                              │
│  app_unified.py  •  18 routes  •  flask-limiter  •  security headers        │
│  File upload handler  •  Path sanitisation  •  Error handlers               │
└──────────┬──────────────────┬──────────────────┬──────────────────┬─────────┘
           │                  │                  │                  │
┌──────────▼──────┐  ┌────────▼────────┐  ┌─────▼──────────┐  ┌───▼─────────┐
│  LAYER 3A       │  │  LAYER 3B       │  │  LAYER 3C      │  │  LAYER 3D   │
│  INGESTION      │  │  RAG ENGINE     │  │  AI CLASSIFIER │  │  SCANNER    │
│                 │  │                 │  │                │  │             │
│ content_        │  │ rag_engine.py   │  │ ai_classifier  │  │ sharepoint_ │
│ extractor.py    │  │                 │  │ .py            │  │ scanner.py  │
│                 │  │ knowledge_      │  │                │  │             │
│ .txt .docx .pdf │  │ base.json       │  │ Gemini API     │  │ file_       │
│ → plain text    │  │ embeddings dict │  │ Ollama fallback│  │ scanner.py  │
│ (in memory)     │  │ cosine sim.     │  │ keyword fallbk │  │             │
└──────────┬──────┘  └────────┬────────┘  └─────┬──────────┘  └─────────────┘
           └──────────────────┴─────────────────┘
                               │  Classification dict (in-memory)
┌──────────────────────────────▼──────────────────────────────────────────────┐
│  LAYER 4 — STORAGE                                                          │
│  /uploads/          orignal uploaded binaries (persisted)                   │
│  /reports/          risk_report_<ts>.json  •  human_verifications.json      │
│  /logs/             application log output                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### File Map — What Each File Contains

| File | Layer | Responsibility |
|---|---|---|
| `app_unified.py` | Application | Flask app factory, all 18 routes, rate limiter, security headers, upload handler, scan orchestration, report export, verification submission |
| `core/ai_classifier.py` | AI | Pre-analysis (regex PII + keyword scoring), prompt building, Gemini API call, Ollama fallback, response parsing, post-validation |
| `core/rag_engine.py` | RAG | Knowledge base loading, embedding generation (sentence-transformers / TF-IDF / keyword), cosine similarity, context retrieval |
| `core/content_extractor.py` | Ingestion | File type detection, size enforcement, text extraction for `.txt` / `.docx` / `.pdf` |
| `core/sharepoint_scanner.py` | Scanning | Site-to-folder mapping, file enumeration, batch classification coordination, summary aggregation |
| `core/file_scanner.py` | Scanning | Low-level file discovery, metadata collection (size, created date, modified date) |
| `knowledge_base.json` | RAG | 10 functional group definitions: descriptions, keywords, document type examples, example phrases |
| `templates/*.html` | Presentation | Jinja2 templates: `home.html`, `browse.html`, `upload.html`, `scan.html`, `dashboard.html`, `unified_interface.html` |
| `templates/brand-styles.css` | Presentation | Custom CSS: PII highlight colours, drawer animations, KPI card styles, sensitivity badge colours |
| `.env` | Config | API keys and runtime secrets (gitignored) |
| `requirements.txt` | Config | All Python dependencies with pinned versions |

---

### Route Map — All 18 Flask Endpoints

#### Page Routes (GET — returns rendered HTML)

| Route | Template | Description |
|---|---|---|
| `GET /` | `home.html` | Landing page / navigation hub |
| `GET /browse` | `browse.html` | Document browser with inline classification and PII highlighting |
| `GET /upload` | `upload.html` | File upload, classify on demand, document viewer drawer |
| `GET /scan` | `scan.html` | Site scanner — select and scan one or all SharePoint sites |
| `GET /dashboard` | `dashboard.html` | Classified records table, KPI cards, Chart.js visualisations |
| `GET /health` | — | Returns `{"status": "healthy"}` — used by hosting platforms |

#### Data API Routes (JSON)

| Route | Method | Rate Limit | Description |
|---|---|---|---|
| `/api/documents` | GET | — | Returns list of all demo documents grouped by site |
| `/api/documents/<path>` | GET | — | Returns file content as plain text; `?full=1` returns full content |
| `/api/classify` | POST | 30/hr · 5/min | Classify a document already on disk by path |
| `/api/upload` | POST | 20/hr · 5/min | Accept file upload, extract text, classify, return result |
| `/api/scan/sites` | GET | — | Returns metadata for all available scan sites |
| `/api/scan/site` | POST | 10/hr · 3/min | Scan all documents in a single named site |
| `/api/scan/all` | POST | — | Scan all sites sequentially |
| `/api/scan/status` | GET | — | Returns current scan progress (used for polling) |
| `/api/scan/ai_insights` | POST | — | Generate a Gemini-powered executive summary of scan results |
| `/api/test/ai` | GET | — | Smoke-test: verifies Gemini API connectivity |
| `/api/export/json` | GET | — | Export full scan results to `reports/risk_report_<ts>.json` |
| `/api/verify` | POST | — | Submit a human reviewer's verification / override of a classification |

---

### Data Flow — Request to Response

Below is the step-by-step trace for the most complex use case: scanning a single site.

```
POST /api/scan/site  { "site_id": "Finance Team" }
       │
       ▼  app_unified.py:api_scan_site()
       1. Validate site_id against MERIDIAN_SITES / scanner.SHAREPOINT_SITES
       2. Build list of all .txt / .docx / .pdf files under site path
       │
       ▼  for each file:
       3. content_extractor.extract_text(file_path)
          ├── check file extension (.txt / .docx / .pdf)
          ├── enforce 5 MB size limit
          ├── extract text → plain string
          └── return (text, None) or (None, error_message)
       │
       4. rag_engine.retrieve(text[:2000], top_k=3)
          ├── embed text[:2000] with SentenceTransformer('all-MiniLM-L6-v2')
          ├── cosine_similarity(doc_vec, group_vec) for each of 10 groups
          ├── sort by score descending
          └── return top-3 [{name, similarity_score, context, keywords}, ...]
       │
       5. ai_classifier.classify(text, filename)
          ├── _pre_analyze(text, filename)
          │     ├── 18 × re.finditer() PII scans
          │     ├── 9-group keyword scoring (domain_scores dict)
          │     ├── filename boost (× 2 per matching keyword)
          │     └── return pre_analysis dict
          ├── _build_prompt(text, filename, pre_analysis=pre_analysis)
          │     ├── smart chunk: text[:10000] + text[-2000] if > 12000 chars
          │     ├── inject pre-analysis cheat-sheet block ("treat as ground truth")
          │     ├── append full group definitions + disambiguation rules
          │     └── return prompt string (~15k chars)
          ├── genai.Client.models.generate_content(model, prompt)
          │     └── on ResourceExhausted/429 → _classify_with_ollama()
          │           └── POST http://localhost:11434/api/generate
          │                 └── on connection error → _fallback_classification()
          ├── _parse_response(response.text)
          │     ├── strip ```json ... ``` fences
          │     ├── re.search r'\{[\s\S]*\}' to extract JSON block
          │     ├── json.loads()
          │     └── fill defaults for missing fields
          └── _post_validate(result, pre_analysis)
                ├── force sensitivity=High if has_high_pii
                ├── merge missed PII types
                ├── override weak group if keyword score gap ≥ 4
                └── bump risk_score floors by PII count
       │
       6. Collect per-file result dict:
          { file_name, functional_group, sensitivity_level, risk_score,
            pii_detected, confidence, reasoning, is_high_risk, ... }
       │
       7. Aggregate across all files:
          { total_docs, high_risk_count, sensitivity_breakdown,
            group_breakdown, average_risk_score, documents: [...] }
       │
       ▼  Flask returns JSON response to browser
       8. JavaScript renders:
          - KPI cards (total docs, high-risk count, avg risk)
          - Sensitivity distribution doughnut (Chart.js)
          - Group breakdown bar chart (Chart.js)
          - Per-document rows with sensitivity badge + PII list
```

---

## 2. AI Pipeline — Detailed Implementation

### Stage 1 — `_pre_analyze(content, file_name)` → `core/ai_classifier.py`

Runs **before** any API call. Returns a `pre_analysis` dict that serves two roles: it is injected into the prompt as deterministic ground truth, and it is used by the post-validator to override LLM hallucinations.

**PII Scanners (18 patterns):**

| Pattern Name | Regex Trigger | Example Match |
|---|---|---|
| SSN | `\b\d{3}-\d{2}-\d{4}\b` | `123-45-6789` |
| Credit Card | Luhn-prefixed 16-digit | `4532-1234-5678-9012` |
| Routing Number | `Routing/ABA/RTN: \d{9}` | `ABA: 021000021` |
| SWIFT/BIC Code | 8–11 char SWIFT format | `CHASUS33` |
| Bank Account | `Account: \d{6,17}` | `Account: 12345678901` |
| IBAN | `[A-Z]{2}\d{2}...` | `GB29NWBK60161331926819` |
| Wire Transfer | `wire transfer` keyword | — |
| Password/Credential | `password=<value>` | — |
| API Key | `api_key=<16+ chars>` | — |
| Secret Key | `secret_key=<value>` | — |
| Email Address | RFC-style email pattern | `john@example.com` |
| Phone Number | `(NNN) NNN-NNNN` | `(212) 555-0100` |
| Employee ID | `EMP-NNN` / `Employee ID: X` | `EMP-00147` |
| Date of Birth | `DOB: MM/DD/YYYY` | `DOB: 01/15/1985` |
| Dollar Amount | `$NNNN+` | `$145,000.00` |
| Salary/Compensation | `salary: $NNN` | `base pay: $95,000` |
| Medical/Health Data | HIPAA / PHI / patient record | — |
| Regulatory Framework | GDPR / CCPA / PCI-DSS / SOX | — |

**Domain Keyword Scoring:**

Each of 9 functional groups has a curated keyword list. For every keyword found in the lowercased document content, the group's score increments by 1. For every keyword found in the filename, the score increments by 2 (filename is a stronger signal). The top-scoring group and its score are passed to the prompt.

**Output structure:**
```python
{
  'pii_hits':      ['SSN: 123-45-6789', 'Salary/Compensation (3 matches)'],
  'pii_count':     2,
  'domain_scores': {'HR': 8, 'Finance and Accounting': 3, ...},
  'top_domain':    'HR',
  'top_score':     8,
  'second_domain': 'Finance and Accounting',
  'second_score':  3,
  'has_high_pii':  True,   # True if SSN/CC/Bank/Routing/Password/API Key detected
}
```

---

### Stage 2 — `_build_prompt(content, file_name, file_size, pre_analysis)` → `core/ai_classifier.py`

**Content windowing:**
```python
if len(content) > 12000:
    content = content[:10000]
              + '\n\n[... middle section omitted ...]\n\n'
              + content[-2000:]
```

**Prompt structure (in order):**

```
[1] ROLE DECLARATION
"You are a document classification expert..."

[2] PRE-ANALYSIS CHEAT-SHEET  ← injected from pre_analysis dict
--- PRE-ANALYSIS SIGNALS (extracted by deterministic regex scan — treat as ground truth) ---
PII / sensitive values detected:
  - SSN: 123-45-6789, 234-56-7890
  - Salary/Compensation (3 matches)

Keyword domain scores:
  HR: 8
  Finance and Accounting: 3
  ...
  Top domain: HR (score 8)  Runner-up: Finance and Accounting (score 3)
--- END PRE-ANALYSIS ---

[3] SENSITIVITY RULES (High / Moderate / Low with exhaustive criteria)

[4] PII DETECTION PATTERNS (11 pattern descriptions for the LLM to scan for)

[5] FUNCTIONAL GROUP DEFINITIONS (all 10 groups with scope, includes, excludes)

[6] DISAMBIGUATION RULES (20+ specific rules for ambiguous document types)

[7] PRIORITY ORDER (1-10: Legal → HR → Finance → IT → Product → Sales
                                → Marketing → Operations → Customer → Outliers)

[8] DOCUMENT METADATA
- Filename: employee_payroll_q1_2026.txt
- Content note: (if truncated)

[9] DOCUMENT CONTENT
<up to 12,000 chars>

[10] CLASSIFICATION INSTRUCTIONS (13 numbered steps referencing pre-analysis)

[11] RESPONSE SCHEMA (exact JSON format, field names, types, and value constraints)
```

**How functional group definitions are injected:**

Each group definition includes: scope sentence, `Includes:` list, `Strong indicators:` list, and `EXCLUDE:` disambiguation rules. These are embedded as plain text directly in the prompt string — not as structured data. The model reads them as instructions.

**How sensitivity rules are applied:**

Three exhaustive bullet-point lists define what constitutes High, Moderate, and Low. The key instruction is:

> *"If the pre-analysis found PII (SSN, credit card, bank account, password, API key, etc.) → sensitivity is HIGH. Do not contradict this."*

This means if the deterministic regex found hard PII, the LLM is explicitly told not to return Low or Moderate — even if it would otherwise assess the document as lower risk.

---

### Stage 3 — Gemini API Call

```python
from google import genai
client = genai.Client(api_key=self.api_key)
response = client.models.generate_content(
    model='gemini-2.0-flash',
    contents=prompt
)
```

**Model settings:**
- Model: `gemini-2.0-flash` (configurable via `GEMINI_MODEL` env var)
- Temperature: Gemini API default (the prompt's tight constraints effectively control variance)
- Max output tokens: Gemini default — the JSON response is ~400–800 tokens
- Retries: 3 attempts with 2-second delay between attempts
- Context window input: up to ~15,000 chars (prompt overhead + 12,000 content chars)

**Quota error detection:**
```python
quota_signals = [
    'resource_exhausted', 'resourceexhausted',
    'quota exceeded', 'rate limit', '429', 'too many requests'
]
if any(s in str(exc).lower() for s in quota_signals):
    → skip remaining retries, go directly to Ollama
```

**Ollama fallback (same prompt, same schema):**
```python
POST http://localhost:11434/api/generate
{
  "model":  "llama3.2",
  "prompt": <identical prompt>,
  "stream": false,
  "options": { "temperature": 0.1, "num_predict": 800 }
}
```

If Ollama is unreachable (connection refused), falls through to keyword-only `_fallback_classification()`.

---

### Stage 4 — `_parse_response(response_text)` → `core/ai_classifier.py`

```python
# 1. Strip markdown code fences if model wrapped output in ```json ... ```
fence = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
if fence:
    json_str = fence.group(1).strip()
else:
    # Extract first {...} block from raw text
    brace = re.search(r'\{[\s\S]*\}', text)
    json_str = brace.group(0).strip()

result = json.loads(json_str)
```

After parsing, missing fields are filled with safe defaults:
```python
result.setdefault('functional_group',    'Outliers / Others')
result.setdefault('sensitivity_level',   'Low')
result.setdefault('confidence',          0.5)
result.setdefault('risk_score',          5.0)
result.setdefault('pii_detected',        [])
result.setdefault('reasoning',           'Classification completed.')
result.setdefault('document_summary',    '')
result.setdefault('confidential_findings', [])
```

---

### Stage 5 — `_post_validate(result, pre_analysis)` → `core/ai_classifier.py`

Four deterministic correction rules applied in order:

```python
# Rule 1: Hard PII → force High sensitivity, risk floor 7.5
if pre_analysis['has_high_pii']:
    result['sensitivity_level'] = 'High'
    result['risk_score'] = max(result['risk_score'], 7.5)

# Rule 2: Merge PII types the LLM missed
for hit in pre_analysis['pii_hits']:
    hit_type = hit.split(':')[0].split('(')[0].strip()
    if hit_type.lower() not in [p.lower() for p in result['pii_detected']]:
        result['pii_detected'].append(hit_type)

# Rule 3: Override weak group assignment when keyword evidence is decisive
if top_score >= 4 and result['functional_group'] in WEAK_CATCH_ALL_GROUPS:
    if keyword_gap >= 4:
        result['functional_group'] = top_domain
        result['reasoning'] = f"[Post-validator overrode...] " + result['reasoning']

# Rule 4: Risk score floors by PII count
if pii_count >= 3: result['risk_score'] = max(result['risk_score'], 8.0)
if pii_count >= 1: result['risk_score'] = max(result['risk_score'], 6.0)
```

**Weak catch-all groups** (trigger override): `Customer / Client Documentation`, `Outliers / Others`, `Operations and Internal Documentation`.

---

## 3. RAG Design

### What Is Implemented

A lightweight in-memory RAG layer that retrieves the top-*k* most semantically similar functional group descriptions for each incoming document. Results are available to the Flask routes for inclusion in API responses and (in `_build_prompt`) as additional context.

### Knowledge Base

`knowledge_base.json` contains 10 entries. Each entry has:

```json
{
  "id": 1,
  "name": "HR & Personnel Management",
  "description": "Manages employee lifecycle including recruitment, onboarding, compensation...",
  "keywords": ["employee", "payroll", "SSN", ...],
  "document_types": ["Performance Improvement Plans", "Payroll reconciliation", ...],
  "example_phrases": ["Employee ID EMP-", "Annual salary", "Direct deposit", ...]
}
```

### Document Chunking Strategy

| Use | Characters Used | Rationale |
|---|---|---|
| RAG retrieval | First 2,000 chars | Opening content (title, author, header) is most discriminative for group matching |
| LLM prompt | First 10,000 + last 2,000 | Covers document introduction and closing sections; middle omitted for very large files |

These two chunking strategies are independent. RAG uses a smaller window for speed; the classifier uses a larger window for accuracy.

### Embedding Generation

**Preferred — `sentence-transformers`:**
```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('all-MiniLM-L6-v2')    # 22M params, 384-dim output

# At startup: embed all 10 group descriptions
group_embeddings = {group_id: model.encode(description) for group_id, desc...}

# At query time: embed document sample
doc_embedding = model.encode(document_text[:2000])
```

**Fallback 1 — TF-IDF (if sentence-transformers not installed):**
```python
from sklearn.feature_extraction.text import TfidfVectorizer
vectorizer = TfidfVectorizer(max_features=200, stop_words='english')
# fit_transform on group descriptions at startup
# transform on document sample at query time
```

**Fallback 2 — Keyword overlap (if sklearn not installed):**  
Direct string intersection between document tokens and each group's keyword list.

### Similarity Search

```python
import numpy as np

def cosine_similarity(vec_a, vec_b):
    # Sentence-transformers returns L2-normalised vectors by default
    # so cosine similarity = dot product
    return float(np.dot(vec_a, vec_b))

# For TF-IDF (sparse vectors):
from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine
```

Results are sorted descending by similarity score. The top-3 groups are returned with their name, description, matched keywords, and similarity score.

### How Context Is Injected

The RAG results are returned by the Flask route as part of the API response under `rag_context`. In the scan and classification views, the browser renders which groups the RAG engine identified as closest matches alongside the AI classification result. 

The `_build_prompt()` method currently uses pre-analysis domain scores (which overlap with RAG signals) as the primary context injection mechanism. A direct integration point exists where RAG similarity scores could be explicitly added to the pre-analysis cheat-sheet block for even tighter grounding.

### Why RAG Improves Consistency

Without RAG, the LLM's group selection depends entirely on its training data's understanding of the group labels. With RAG:
- The model sees quantified evidence of which group descriptions are *semantically closest* to the actual document text
- This counteracts the LLM's tendency to assign ambiguous documents to large catch-all groups ("Customer / Client Documentation")
- RAG similarity scores provide a complementary signal to keyword frequency counts, capturing semantic similarity even when exact keyword matches are absent

---

## 4. Risk Scoring Logic

### Two Scoring Paths

**Path A — AI-Assisted (primary, used when Gemini or Ollama is available)**

The LLM returns `risk_score` (0–10) in its JSON response. The prompt instructs the model to use this rubric:

```
High sensitivity + 3+ PII types → 9–10
High sensitivity + 1–2 PII types → 7–8
Moderate sensitivity → 3–6
Low sensitivity → 0–3
```

The post-validator then applies deterministic floors:

```python
# Floor matrix
if has_high_pii:          risk_score = max(risk_score, 7.5)
if pii_count >= 3:        risk_score = max(risk_score, 8.0)
if pii_count >= 1:        risk_score = max(risk_score, 6.0)
```

These floors ensure that regardless of what value the LLM returns, a document with confirmed hard PII can never score below 6.0, and a document with 3+ confirmed PII types can never score below 8.0.

**Path B — Heuristic (keyword fallback when no LLM is available)**

A base risk value is assigned by functional group and sensitivity tier, then a deterministic jitter derived from the filename's MD5 hash is applied:

```python
# Base risks by group (examples)
# HR payroll → 8.5
# Finance banking → 8.0
# IT credentials → 6.9 – 8.5
# Legal → 7.5 – 8.0
# Customer/Client → 5.8
# Operations → 3.5
# Marketing → 3.0

seed   = int(hashlib.md5(filename.encode()).hexdigest()[:6], 16)
jitter = (seed % 20 - 10) / 10.0        # deterministic range: -1.0 to +1.0
raw    = min(10.0, max(1.0, base_risk + jitter))
score  = round(raw * 10) / 10
```

The MD5 seed guarantees the same filename always produces the same jitter, so repeated scans of the same file produce identical scores in the absence of an LLM.

### High-Risk Threshold

A document is flagged as `is_high_risk = True` when **any** of these conditions is met:

```python
is_high_risk = (
    risk_score >= 7.0
    or sensitivity_level == 'High'
    or len(pii_detected) > 0
)
```

This intentionally errs on the side of over-flagging — the cost of missing a high-risk document is higher than the cost of reviewing a false positive.

### Weight Assumptions and Rationale

| Factor | Weight/Mechanism | Rationale |
|---|---|---|
| Sensitivity = High | Floor: risk ≥ 7.5 | Regulatory data (PII, PHI, financial credentials) carries inherent legal exposure regardless of document type |
| 3+ PII types present | Floor: risk ≥ 8.0 | Multiple PII types indicate a data-dense document — maximally likely to cause harm if disclosed |
| 1–2 PII types present | Floor: risk ≥ 6.0 | Some personal data exposure; moderate-to-high risk even if document is otherwise routine |
| Functional group base risk | 3.0–8.5 | Groups containing regulated data (payroll, banking, HR) start at higher risk than operational or marketing documents |
| MD5 jitter | ±1.0 | Adds visual realism to demo data; makes score distribution look naturally varied |

### Known Limitations

- Base risk values are manually assigned — not derived from incident data or statistical modelling
- Document age is not factored in (a 5-year-old payroll file in a shared drive is not penalised more than a new one)
- Breadth of access (how many users can read the document) is not modelled
- Risk is per-document, not aggregate (a site with 100 high-risk HR files is not scored differently from one with 1)

---

## 5. Database / Storage Design

### Storage Strategy

The PoC deliberately avoids a relational database to minimise infrastructure requirements. All classification results are **ephemeral** — they exist in Python dicts during a request and are returned to the browser in the JSON response. Nothing about a classification is automatically written to disk.

Three categories of data **are** persisted to disk:

---

### 1. Uploaded Documents — `/uploads/`

**Written by:** `POST /api/upload`  
**Format:** Original file binary  
**Naming:** `<YYYYMMDD_HHMMSS>_<secure_filename>`  
**Example:** `20260227_143022_employee_payroll_q1_2026.txt`  
**Purpose:** Allows the inline document viewer to re-fetch the file after classification  
**Retention:** Indefinite (no automatic cleanup in PoC)

**Code:**
```python
filename = secure_filename(file.filename)         # sanitise
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
filename  = timestamp + filename
filepath  = UPLOAD_FOLDER / filename
file.save(str(filepath))
```

---

### 2. Exported Risk Reports — `/reports/risk_report_<timestamp>.json`

**Written by:** `GET /api/export/json`  
**Format:** JSON  
**Schema:**
```json
{
  "exported_at":   "2026-02-27T14:30:00Z",
  "total_documents": 42,
  "high_risk_count": 11,
  "sensitivity_breakdown": { "High": 11, "Moderate": 19, "Low": 12 },
  "documents": [
    {
      "file_name":        "employee_payroll_q1_2026.txt",
      "file_path":        "demo_sharepoint/HR_Department/...",
      "file_size":        14820,
      "functional_group": "HR",
      "sensitivity_level":"High",
      "risk_score":       9.1,
      "is_high_risk":     true,
      "pii_detected":     ["SSN", "Employee ID", "Salary/Compensation"],
      "confidence":       0.94,
      "reasoning":        "..."
    }
  ]
}
```

---

### 3. Human Verification Records — `/reports/human_verifications.json`

**Written by:** `POST /api/verify`  
**Format:** JSON array (append-only)  
**Schema:**
```json
[
  {
    "document_id":              "employee_payroll_q1_2026.txt",
    "original_classification":  "HR",
    "verified_classification":  "HR",
    "reviewer_notes":           "Confirmed — payroll file",
    "is_confirmed":             true,
    "reviewed_at":              "2026-02-27T14:35:00Z"
  }
]
```

---

### What Is Intentionally NOT Stored

| Data | Reason Not Stored |
|---|---|
| Extracted document text | Privacy by design — text is processed in memory and immediately discarded |
| Full classification result per scan | Results are returned to the browser; no automatic persistence to DB |
| API keys | Only in environment variables; never logged or written to any file |
| User identity / session data | No authentication system in PoC |
| Embedding vectors | Recomputed from knowledge_base.json at every server startup |
| Intermediate LLM prompt/response | Discarded after parsing; never logged at INFO level |
| IP addresses (rate limiter) | flask-limiter uses in-memory storage only; resets on restart |

---

### Production Schema (What This Would Become)

In a production deployment, the following relational schema would replace flat-file storage:

```sql
-- Documents table (document registry)
CREATE TABLE documents (
    id              SERIAL PRIMARY KEY,
    file_name       VARCHAR(255)     NOT NULL,
    file_path       TEXT             NOT NULL,
    file_size       INTEGER,
    file_hash       VARCHAR(64),          -- SHA-256 for dedup / change detection
    source_site     VARCHAR(100),
    created_date    TIMESTAMP,
    modified_date   TIMESTAMP,
    ingested_at     TIMESTAMP DEFAULT NOW()
);

-- Classification results (one row per classification run)
CREATE TABLE classification_results (
    id                  SERIAL PRIMARY KEY,
    document_id         INTEGER REFERENCES documents(id),
    classified_at       TIMESTAMP DEFAULT NOW(),
    functional_group    VARCHAR(100)  NOT NULL,
    sensitivity_level   VARCHAR(20)   NOT NULL CHECK (sensitivity_level IN ('Low','Moderate','High')),
    confidence          NUMERIC(4,3),
    risk_score          NUMERIC(4,1),
    is_high_risk        BOOLEAN,
    pii_detected        JSONB,        -- array of PII type strings
    reasoning           TEXT,
    document_summary    TEXT,
    model_used          VARCHAR(50),  -- 'gemini-2.0-flash', 'ollama/llama3.2', 'keyword_fallback'
    classification_status VARCHAR(20)
);

-- Human verifications (reviewer overrides)
CREATE TABLE human_verifications (
    id                      SERIAL PRIMARY KEY,
    classification_result_id INTEGER REFERENCES classification_results(id),
    reviewer_id             VARCHAR(100),   -- AD username in production
    original_group          VARCHAR(100),
    verified_group          VARCHAR(100),
    reviewer_notes          TEXT,
    is_confirmed            BOOLEAN,
    reviewed_at             TIMESTAMP DEFAULT NOW()
);

-- Scan logs (one row per site scan run)
CREATE TABLE scan_logs (
    id              SERIAL PRIMARY KEY,
    site_name       VARCHAR(100),
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    total_docs      INTEGER,
    success_count   INTEGER,
    error_count     INTEGER,
    triggered_by    VARCHAR(100)    -- user identity in production
);
```

---

## 6. Security Design

### Raw Content Handling

Document text is **never written to disk**. The processing pipeline:

```python
# content_extractor.py — returns string, writes nothing
text, error = extract_text(str(full_path))

# Passed through rag_engine and classifier as a Python string in memory
rag_results   = rag_engine.retrieve(text, top_k=3)
classification = classifier.classify(text, filename)

# After classify() returns, `text` goes out of scope and is garbage collected
# Nothing referencing it is stored anywhere
```

The only exception is the upload viewer: the browser can request `/api/documents/<path>?full=1` to re-read a file for display. This reads from the original file on disk, not from any stored copy of extracted text.

### API Key Management

```
┌─────────────────────────────────────────────────────────────┐
│  .env  (gitignored, never committed)                        │
│  GEMINI_API_KEY=AIza...                                     │
│  GEMINI_API_KEY_2=AIza...  (backup)                         │
│  FLASK_SECRET_KEY=<256-bit hex>                             │
│  OLLAMA_URL=http://localhost:11434                           │
└──────────────────────────┬──────────────────────────────────┘
                           │  python-dotenv load_dotenv()
                           ▼
               os.getenv('GEMINI_API_KEY')      ← read at startup
               stored in AIClassifier.api_key   ← server-side only
               NEVER sent to browser
               NEVER included in any log message
               NEVER included in any API response
```

The `.env` file is in `.gitignore`. A documented `.env.example` with placeholder values is tracked in git instead.

On hosted platforms (Render, Railway, Heroku, etc.), secrets are set as **platform environment variables** — the `.env` file is not deployed.

### Flask Secret Key

Required for Flask session security. Generated and managed as follows:

```python
_secret = os.getenv('FLASK_SECRET_KEY')
if not _secret:
    import secrets
    _secret = secrets.token_hex(32)          # 256-bit random key
    logger.warning("FLASK_SECRET_KEY not set — sessions won't persist across restarts")
app.secret_key = _secret
```

**Generate a production key:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Rate Limiting

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],          # no default; per-route only
    storage_uri='memory://',    # single-process; upgrade to redis:// for multi-worker
)

@app.route('/api/classify', methods=['POST'])
@limiter.limit('30 per hour; 5 per minute')
def api_classify(): ...
```

**429 response (JSON, not HTML):**
```python
@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({
        'error': 'Too many requests. Please wait before trying again.',
        'retry_after': str(e.description)
    }), 429
```

### HTTP Security Headers

Set on **every** response via `@app.after_request`:

```python
@app.after_request
def _security_headers(response):
    response.headers['X-Content-Type-Options']  = 'nosniff'
    response.headers['X-Frame-Options']         = 'SAMEORIGIN'
    response.headers['X-XSS-Protection']        = '1; mode=block'
    response.headers['Referrer-Policy']         = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy']      = 'geolocation=(), microphone=(), camera=()'
    # Uncomment once HTTPS is confirmed:
    # response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response
```

### Path Traversal Prevention

Upload and classify routes validate that every resolved file path is within the allowed directories before opening:

```python
full_path = (project_root / file_path).resolve()

# Block any path outside demo_sharepoint/ or uploads/
if not (str(full_path).startswith(str(project_root / 'demo_sharepoint'))
     or str(full_path).startswith(str(UPLOAD_FOLDER))):
    return jsonify({'error': 'Access denied'}), 403
```

`werkzeug.utils.secure_filename()` is applied to all uploaded filenames before saving.

---

## 7. Rebuild Instructions

These instructions allow a separate engineering team to recreate the prototype from scratch on a clean machine.

### Prerequisites

| Requirement | Minimum Version | Notes |
|---|---|---|
| Python | 3.11 | 3.10 will also work |
| pip | 23+ | Bundled with Python 3.11 |
| Git | Any | For cloning |
| Google Gemini API key | — | https://aistudio.google.com/app/apikey — free tier available |
| Ollama (optional) | 0.1+ | https://ollama.com/download — only needed for offline fallback |

---

### Step 1 — Clone / Create Project Structure

```
capstone_ai/
├── app_unified.py
├── knowledge_base.json
├── requirements.txt
├── .env                          ← create from .env.example
├── .env.example
├── core/
│   ├── __init__.py
│   ├── ai_classifier.py
│   ├── content_extractor.py
│   ├── file_scanner.py
│   ├── rag_engine.py
│   └── sharepoint_scanner.py
├── templates/
│   ├── brand-styles.css
│   ├── home.html
│   ├── browse.html
│   ├── upload.html
│   ├── scan.html
│   ├── dashboard.html
│   └── unified_interface.html
├── demo_sharepoint/
│   ├── Finance_Site/
│   ├── HR_Site/
│   ├── HR_Department/
│   ├── IT_Site/
│   ├── IT_Systems/
│   ├── Legal_Site/
│   ├── Client_Site/
│   ├── Operations_Site/
│   ├── Marketing_Site/
│   ├── Meridian_Client_Site/
│   ├── Meridian_Finance_Site/
│   └── Meridian_HR_Site/
├── uploads/                      ← created automatically at startup
├── reports/                      ← created automatically at startup
└── logs/                         ← created automatically at startup
```

---

### Step 2 — Create and Activate Virtual Environment

**Windows (PowerShell):**
```powershell
cd capstone_ai
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux:**
```bash
cd capstone_ai
python3 -m venv .venv
source .venv/bin/activate
```

---

### Step 3 — Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt`:
```
Flask==2.3.3
Werkzeug==2.3.7
Jinja2==3.1.2
python-docx==0.8.11
openpyxl==3.1.2
PyPDF2==3.0.1
python-pptx==0.6.21
google-generativeai==0.3.0
sentence-transformers==2.2.2
numpy==1.24.3
python-dotenv==1.0.0
flask-limiter==3.5.0
requests==2.31.0
```

> **Note on `google-generativeai` vs `google-genai`:**  
> The classifier uses `from google import genai` (the newer `google-genai` SDK). If `google-generativeai` does not provide this, install the correct package:
> ```bash
> pip install google-genai
> ```

---

### Step 4 — Configure Environment Variables

Copy `.env.example` to `.env` and fill in real values:

```bash
cp .env.example .env
```

Edit `.env`:
```dotenv
# Required
GEMINI_API_KEY=AIzaSy...your_real_key_here...

# Optional: second key for failover
GEMINI_API_KEY_2=AIzaSy...backup_key...

# Optional: change model (default: gemini-2.0-flash)
GEMINI_MODEL=gemini-2.0-flash

# Required for production sessions — generate with:
# python -c "import secrets; print(secrets.token_hex(32))"
FLASK_SECRET_KEY=put_a_64_char_hex_string_here

# Flask runtime settings
FLASK_ENV=development
FLASK_DEBUG=0

# Optional: local Ollama fallback
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

---

### Step 5 — (Optional) Set Up Ollama Local LLM

Skip this step if you always have Gemini API access.

```bash
# 1. Download Ollama installer from https://ollama.com/download
# 2. Run installer (adds 'ollama' to PATH)
# 3. Pull the default model (~2 GB):
ollama pull llama3.2
# 4. Ollama starts automatically on http://localhost:11434
```

Verify it works:
```bash
curl http://localhost:11434/api/tags
```

---

### Step 6 — Populate Demo SharePoint Data

The `demo_sharepoint/` directory contains synthetic `.txt` files simulating real SharePoint documents. Each subdirectory represents a SharePoint site:

```
demo_sharepoint/
  Finance_Site/        → financial reports, budgets, tax documents
  HR_Site/             → employee handbook, performance reviews, benefits
  HR_Department/       → payroll files (high sensitivity)
  IT_Site/             → system architecture, technical specs, network plans
  IT_Systems/          → access control matrix, cloud config, credentials
  Legal_Site/          → contracts, NDAs, compliance documents
  Client_Site/         → client case studies, executive summaries
  Operations_Site/     → SOPs, operational reports
  Marketing_Site/      → campaign materials, brand guides
  Meridian_Client_Site/  → consulting firm demo: client engagements
  Meridian_Finance_Site/ → consulting firm demo: billing and finance
  Meridian_HR_Site/      → consulting firm demo: HR records
```

Each `.txt` file should contain realistic synthetic content for its document type. Files should include a mix of:
- Low risk: generic SOPs, marketing copy, general policies
- Moderate risk: internal strategies, budget forecasts, performance reviews
- High risk: payroll files with SSNs, banking details, access credentials

---

### Step 7 — Verify knowledge_base.json

The RAG engine requires `knowledge_base.json` in the project root. It must contain a top-level `functional_groups` array with 10 entries, each having: `id`, `name`, `description`, `keywords`, `document_types`, `example_phrases`.

```bash
python -c "import json; kb = json.load(open('knowledge_base.json')); print(len(kb['functional_groups']), 'groups loaded')"
# Expected output: 10 groups loaded
```

---

### Step 8 — Start the Server

**Development (foreground, with auto-reload):**
```bash
# Windows
.venv\Scripts\python.exe app_unified.py

# macOS / Linux
.venv/bin/python app_unified.py
```

**Development (background, PowerShell):**
```powershell
Start-Job -ScriptBlock {
    Set-Location C:\path\to\capstone_ai
    & .venv\Scripts\python.exe app_unified.py *>&1 | Out-Null
}
Start-Sleep 5
netstat -ano | findstr ":5000.*LISTEN"
```

**Expected startup output:**
```
================================================================================
UNIFIED DOCUMENT CLASSIFICATION INTERFACE
================================================================================

 Web Interface: http://localhost:5000
 Upload Folder: .../uploads
 Documents Folder: .../demo_sharepoint

[OK] RAG Engine initialized
[OK] AI Classifier ready
[OK] SharePoint Scanner configured

================================================================================
```

---

### Step 9 — Smoke Tests

**Test 1 — Health check:**
```bash
curl http://localhost:5000/health
# Expected: {"status": "healthy"}
```

**Test 2 — AI connectivity:**
```bash
curl http://localhost:5000/api/test/ai
# Expected: {"status": "success", "model": "gemini-2.0-flash", ...}
```

**Test 3 — Classify a demo document:**
```bash
curl -X POST http://localhost:5000/api/classify \
  -H "Content-Type: application/json" \
  -d '{"file_path": "demo_sharepoint/HR_Department/employee_payroll_q1_2026.txt"}'
# Expected: {"status": "success", "classification": {"functional_group": "HR", "sensitivity_level": "High", ...}}
```

**Test 4 — Upload and classify:**
```bash
curl -X POST http://localhost:5000/api/upload \
  -F "file=@demo_sharepoint/Finance_Site/Q1_Financial_Report.txt"
# Expected: {"status": "success", "classification": {...}, "file_path": "uploads/..."}
```

**Test 5 — Scan a site:**
```bash
curl -X POST http://localhost:5000/api/scan/site \
  -H "Content-Type: application/json" \
  -d '{"site_id": "HR Records"}'
# Expected: {"status": "success", "documents": [...], "summary": {...}}
```

**Test 6 — Python import check:**
```bash
python -c "
from core.ai_classifier import AIClassifier
from core.rag_engine import RAGEngine
from core.content_extractor import extract_text
c = AIClassifier()
print('Classifier OK - model:', c.model)
print('Ollama URL:', c.ollama_url)
r = RAGEngine()
print('RAG OK - groups:', len(r.groups))
"
```

---

### Step 10 — Access the Interface

Open a browser and navigate to:

| URL | Page |
|---|---|
| `http://localhost:5000` | Home / navigation hub |
| `http://localhost:5000/browse` | Browse and classify demo documents |
| `http://localhost:5000/upload` | Upload and classify your own documents |
| `http://localhost:5000/scan` | Scan full SharePoint sites |
| `http://localhost:5000/dashboard` | View all classified records and risk dashboard |

---

### Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `ImportError: cannot import name 'genai' from 'google'` | Wrong SDK version | `pip install google-genai` |
| `GEMINI_API_KEY not set` warning | `.env` not loaded | Check `.env` file exists in project root; `load_dotenv()` is called at startup |
| Port 5000 already in use | Previous instance still running | `Get-Process python \| Stop-Process -Force` (Windows) or `pkill -f app_unified.py` |
| RAG initialises with TF-IDF instead of sentence-transformers | sentence-transformers install failed | `pip install sentence-transformers` (requires ~600 MB) |
| `FileNotFoundError: knowledge_base.json` | Wrong working directory | Run `python app_unified.py` from the `capstone_ai/` root |
| Classification returns `fallback` status | No API key + Ollama not running | Set `GEMINI_API_KEY` in `.env` OR start Ollama with `ollama serve` |
| Rate limit 429 after rapid testing | flask-limiter triggered | Wait 1 minute, or disable limits temporarily with `FLASK_DEBUG=1` |

---

*End of Technical Reference*
