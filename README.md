# 🔍 AI Document Classification System

A unified document classification system for scanning, analyzing, and risk-scoring documents using Google Gemini AI.

## 🎯 What This System Does

- **Document Classification**: Categorizes documents into 10 business functional groups (HR, Finance, Legal, etc.)
- **Sensitivity Analysis**: Assigns Low/Moderate/High sensitivity levels based on content
- **Risk Assessment**: Calculates risk scores (0-10) and identifies PII/sensitive data
- **Unified Web Interface**: Browse, upload, classify documents and run site-wide scans
- **RAG-Enhanced Classification**: Uses local embeddings for context-aware classification

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Set Up Environment
```bash
# Copy example environment file
cp .env.example .env

# Edit .env and add your Google Gemini API key
GEMINI_API_KEY=your_api_key_here
```

### 3. Run the Application
```bash
python app_unified.py
```

Visit **http://localhost:5000** to access the web interface.

## 📁 Project Structure

```
capstone_ai/
├── README.md                      # This file
├── app_unified.py                 # Main Flask application
├── requirements.txt               # Python dependencies
├── .env                          # Environment variables (API keys)
├── knowledge_base.json           # Functional group definitions
│
├── core/                         # Core processing modules
│   ├── ai_classifier.py         # Google Gemini integration
│   ├── content_extractor.py     # Document parsing (.txt, .pdf, .docx)
│   ├── rag_engine.py           # Context retrieval system
│   └── sharepoint_scanner.py    # Batch document processing
│
├── templates/
│   └── unified_interface.html    # Web interface
│
├── demo_sharepoint/              # Demo documents (113 files)
│   ├── Finance_Team/
│   ├── HR_Department/
│   ├── IT_Security/
│   └── ... (6 SharePoint sites)
│
├── uploads/                      # File upload directory
└── logs/                         # Application logs
```

## 🎮 Using the Interface

### Browse Tab
- View all 113 demo documents across 6 SharePoint sites
- Documents start as "UNCLASSIFIED" until manually classified
- Status badges show classification state and risk level
- PII warnings displayed for sensitive documents

### Upload Tab
- Upload .txt, .pdf, or .docx files (max 5MB)
- Automatic classification on upload
- Risk assessment and confidence scores displayed

### Classify Tab
- Select a document from Browse tab
- Run AI classification with detailed results:
  - Functional group assignment with confidence %
  - Sensitivity level (Low/Moderate/High) with confidence %
  - Risk score (0-10) with visual indicators
  - PII detection and types found

### Scan Tab
- Batch process all documents across all sites
- Risk-prioritized results showing critical documents first
- Sensitive data alerts for PII-containing documents
- Summary statistics and distribution charts

## 🏗️ Functional Groups

The AI classifies documents into these business categories:

1. **HR (Human Resources)** - Employee records, payroll, benefits
2. **Finance and Accounting** - Financial reports, budgets, transactions  
3. **Legal + Compliance** - Contracts, policies, regulatory docs
4. **Customer / Client Documentation** - Client deliverables, case files
5. **Sales & Business Development** - Pipeline reports, proposals
6. **Marketing & Communications** - Campaigns, press releases, brand content
7. **IT & Systems** - Architecture docs, configs, technical specs
8. **Product Development / R&D** - Roadmaps, specifications, engineering docs
9. **Operations and Internal Documentation** - SOPs, procedures, training materials

## 🛡️ Risk Assessment

**Risk Scoring (0-10):**
- **8.0-10.0**: Critical risk - Contains regulated data, PII, financial accounts
- **6.0-8.0**: High risk - Business-sensitive, internal confidential data
- **4.0-6.0**: Medium risk - Internal business information
- **0.0-4.0**: Low risk - Public or non-sensitive content

**PII Detection:**
- Social Security Numbers (SSNs)
- Credit card numbers
- Bank account information
- Employee IDs with personal data
- Health/medical information
- API keys and credentials

## 🔧 Configuration

### Environment Variables (.env)
```bash
GEMINI_API_KEY=your_google_gemini_api_key
DEBUG=False
HOST=127.0.0.1
PORT=5000
```

### Functional Groups (knowledge_base.json)
Contains detailed definitions for each business functional group used by the AI classifier.

## 🎯 Key Features

- ✅ **No Raw Content Storage** - Only metadata and classifications stored
- ✅ **Custom Styled Popups** - No system alerts, beautiful notifications
- ✅ **Confidence Metrics** - Separate confidence scores for group and sensitivity
- ✅ **Visual Risk Indicators** - Color-coded badges and progress bars  
- ✅ **Smart Classification** - AI avoids "Others" category, forces proper grouping
- ✅ **Responsive Design** - Modern web interface with smooth animations

## 📝 Demo Data

Includes 113 realistic business documents across 6 simulated SharePoint sites:
- Finance Team (19 documents)
- HR Department (18 documents) 
- IT Security (19 documents)
- Legal Compliance (19 documents)
- Marketing Communications (19 documents)
- Operations Management (19 documents)

## 🚨 Security Notes

- Add your `.env` file to `.gitignore`
- Never commit API keys to version control
- Demo documents contain simulated PII for testing only
- This is a proof-of-concept system - harden before production use

## 🐛 Troubleshooting

**"No API key" errors**: Ensure `GEMINI_API_KEY` is set in `.env` file
**Port conflicts**: Change `PORT=5001` in `.env` if port 5000 is busy
**Module import errors**: Run `pip install -r requirements.txt`
**File upload issues**: Check file size (max 5MB) and format (.txt/.pdf/.docx)

## 📄 License

This is a proof-of-concept system for educational and demonstration purposes.
│
├── core/                          # Business logic modules
│   ├── __init__.py
│   ├── file_scanner.py            # Scans simulated SharePoint folder
│   ├── content_extractor.py       # Extracts text from documents
│   ├── ai_classifier.py           # Calls Gemini API for classification
│   ├── embeddings.py              # Local embeddings for RAG layer
│   ├── risk_calculator.py         # Computes risk scores
│   └── database.py                # SQLite operations (metadata only)
│
├── config/                        # Configuration
│   ├── __init__.py
│   ├── settings.py                # App settings & constants
│   └── gemini_config.py           # Gemini API configuration
│
├── data/                          # Data storage
│   ├── app.db                     # SQLite database (created at runtime)
│   └── simulated_sharepoint/      # Simulated document library
│       ├── HR/
│       ├── Finance/
│       ├── Legal_Compliance/
│       ├── Customer_Documentation/
│       ├── Sales_BizDev/
│       ├── Marketing/
│       ├── IT_Systems/
│       ├── Product_RnD/
│       ├── Operations/
│       └── Outliers/
│
└── logs/                          # Application logs
    └── app.log
```

## Quick Start

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment**:
   ```bash
   cp .env.example .env
   # Add your Gemini API key to .env
   ```

3. **Initialize database**:
   ```bash
   python run.py --init-db
   ```

4. **Scan and classify**:
   ```bash
   python run.py --scan-all
   ```

5. **Run dashboard**:
   ```bash
   python run.py
   # Open http://localhost:5000
   ```

## 10 Functional Groups

1. **HR** — Employee records, benefits, payroll
2. **Finance and Accounting** — Financial statements, budgets, invoices
3. **Legal + Compliance** — Contracts, policies, compliance docs
4. **Customer / Client Documentation** — Customer agreements, case studies
5. **Sales & Business Development** — Proposals, leads, partnerships
6. **Marketing & Communications** — Campaigns, branding, communications
7. **IT & Systems** — Infrastructure, security, technical docs
8. **Product Development / R&D** — Designs, research, development docs
9. **Operations and Internal Documentation** — Procedures, meetings, internal notes
10. **Outliers / Others** — Unclassified or miscellaneous

## Data Flow

```
[Simulated SharePoint Folder]
           ↓
     [File Scanner]
           ↓
  [Content Extractor]
           ↓
  [Embeddings Layer] ←→ [Local Embeddings DB]
           ↓
   [AI Classifier] → [Gemini API]
           ↓
  [Risk Calculator]
           ↓
  [Database Writer] → [SQLite: Metadata Only]
           ↓
     [Dashboard UI]
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed module documentation.

## Features (PoC Scope)

- ✅ Document scanning from simulated SharePoint
- ✅ Multi-format content extraction (PDF, DOCX, XLSX, TXT, PPTX)
- ✅ AI-powered classification into 10 categories
- ✅ Sensitivity level estimation (Low/Moderate/High)
- ✅ Risk scoring (0-100)
- ✅ Metadata dashboard with filtering & sorting
- ✅ Local RAG layer using embeddings
- ✅ No raw content storage

## Out of Scope

- ❌ Real Microsoft Graph/SharePoint integration
- ❌ User authentication & authorization
- ❌ Real-time monitoring
- ❌ Document remediation workflows
- ❌ Advanced analytics or ML models

## Development Notes

- Each module has single responsibility
- Database stores **only** metadata & classifications
- Document content is extracted, processed, then discarded
- Gemini API handles all AI logic
- Local embeddings support RAG-based retrieval

## License

Internal PoC — Not for production use

---

**Started**: February 2026  
**Status**: Initial Design Phase
