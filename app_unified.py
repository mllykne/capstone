"""
Unified Document Classification Interface

Single Flask app that consolidates:
- Document browser & upload
- Individual document testing
- Full site scanning
- Results viewing

Run with: python app_unified.py
Access at: http://localhost:5000
"""

import os
import re
import json
import time
import logging
import hashlib
import math
from pathlib import Path
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, jsonify, send_file
import sys

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from core.content_extractor import extract_text
from core.rag_engine import RAGEngine
from core.ai_classifier import AIClassifier
from core.sharepoint_scanner import SharePointScanner

# Configuration
UPLOAD_FOLDER = project_root / 'uploads'
REPORTS_FOLDER = project_root / 'reports'
ALLOWED_EXTENSIONS = {'txt', 'docx', 'pdf'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# Create folders if they don't exist
UPLOAD_FOLDER.mkdir(exist_ok=True)
REPORTS_FOLDER.mkdir(exist_ok=True)

# Initialize Flask app
app = Flask(__name__, template_folder='templates')
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE
app.config['JSON_SORT_KEYS'] = False

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# ── Security: secret key (required for sessions & CSRF tokens) ────────────────
_secret = os.getenv('FLASK_SECRET_KEY')
if not _secret:
    import secrets
    _secret = secrets.token_hex(32)
    logger.warning("FLASK_SECRET_KEY not set — using a random key (sessions won't persist across restarts). Set it in .env for production.")
app.secret_key = _secret

# ── Rate limiting — protect Gemini API quota from abuse ───────────────────────
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],          # no blanket limit; apply per-route only
    storage_uri='memory://',
)

# ── Security headers on every response ───────────────────────────────────────
@app.after_request
def _security_headers(response):
    response.headers['X-Content-Type-Options']  = 'nosniff'
    response.headers['X-Frame-Options']         = 'SAMEORIGIN'
    response.headers['X-XSS-Protection']        = '1; mode=block'
    response.headers['Referrer-Policy']         = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy']      = 'geolocation=(), microphone=(), camera=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "font-src 'self' https://cdnjs.cloudflare.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    # Only send HSTS once you have HTTPS
    # response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# ── Reject oversized JSON payloads before any route logic runs ────────────────
@app.before_request
def _limit_json_payload():
    """Block JSON request bodies over 1 MB to prevent DoS via huge payloads."""
    if request.content_type and 'application/json' in request.content_type:
        if request.content_length and request.content_length > 1 * 1024 * 1024:
            return jsonify({'error': 'Request payload too large'}), 413

# Global instances
rag_engine = RAGEngine()
classifier = AIClassifier()
scanner = SharePointScanner()


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

# Allowed actions for human verification endpoint
_VERIFY_ACTIONS = {'accept', 'reject', 'correct'}

# Regex to strip CRLF and other control characters used in log/header injection
_CTRL_RE = re.compile(r'[\r\n\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

def sanitize_str(value, max_len: int = 500) -> str:
    """Strip control characters and truncate. Returns empty string for non-strings."""
    if not isinstance(value, str):
        return ''
    cleaned = _CTRL_RE.sub('', value)
    return cleaned[:max_len]

def sanitize_file_path(value, max_len: int = 300) -> str:
    """Sanitize a user-supplied file path string."""
    if not isinstance(value, str):
        return ''
    # Strip null bytes, control chars, shell metacharacters
    cleaned = _CTRL_RE.sub('', value)
    cleaned = re.sub(r'[;|&`$!]', '', cleaned)
    return cleaned[:max_len]

def allowed_file(filename):
    """Check if file type is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_document_list():
    """Get list of all demo documents grouped by site."""
    documents = {}
    
    for site_name, site_path in scanner.SHAREPOINT_SITES.items():
        if isinstance(site_path, str):
            site_dir = Path(site_path)
        else:
            site_dir = site_path
        
        if site_dir.exists():
            files = sorted(site_dir.rglob('*.*'))
            files = [f for f in files if f.is_file() and allowed_file(f.name)]
            documents[site_name] = [
                {
                    'name': f.name,
                    'path': str(f.relative_to(project_root)).replace('\\', '/'),
                    'size': f.stat().st_size,
                    'size_mb': round(f.stat().st_size / (1024 * 1024), 2)
                }
                for f in files
            ]
    
    return documents


# ============================================================================
# HOME & MAIN INTERFACE
# ============================================================================

@app.route('/')
def home():
    """Main landing page."""
    return render_template('home.html')


@app.route('/browse')
def browse():
    """Document browser page."""
    return render_template('browse.html')


@app.route('/upload')
def upload():
    """Upload & classify page."""
    return render_template('upload.html')


@app.route('/scan')
def scan():
    """Site scanner page."""
    sites = []
    for name, meta in MERIDIAN_SITES.items():
        path = meta['path']
        doc_count = _count_site_docs(path)
        sites.append({
            'id': name,
            'name': name,
            'description': meta['description'],
            'icon': meta['icon'],
            'color': meta['color'],
            'url': meta['url'],
            'doc_count': doc_count,
            'path': str(path),
            'exists': path.exists(),
        })
    return render_template('scan.html', sites=sites, sites_json=json.dumps(sites))


@app.route('/dashboard')
def dashboard():
    """Classified records dashboard."""
    return render_template('dashboard.html')


@app.route('/health')
def health():
    """Health check."""
    return jsonify({
        'status': 'healthy',
        'service': 'Unified Document Classification Interface'
    })


# ============================================================================
# DOCUMENT BROWSER API
# ============================================================================

@app.route('/api/documents')
def api_documents():
    """Get all available documents with classification status."""
    documents = get_document_list()
    
    # Flatten and add metadata - mark all as unclassified initially
    all_docs = []
    for site_name, docs in documents.items():
        for doc in docs:
            doc['site'] = site_name
            doc['status'] = 'unclassified'  # All start as unclassified
            doc['classification'] = None
            all_docs.append(doc)
    
    return jsonify({
        'total': len(all_docs),
        'by_site': {k: len(v) for k, v in documents.items()},
        'documents': all_docs,
        'status_summary': {
            'unclassified': len(all_docs),
            'classified': 0
        }
    })


@app.route('/api/documents/<path:file_path>')
def api_document_preview(file_path):
    """Get document preview/content."""
    try:
        # Normalize path separators
        file_path = file_path.replace('\\', '/')
        full_path = project_root / file_path
        
        # Security check
        if not full_path.exists() or not full_path.is_file():
            return jsonify({'error': 'File not found'}), 404
        
        # Check if within demo_sharepoint or uploads
        if not (str(full_path).startswith(str(project_root / 'demo_sharepoint')) or 
                str(full_path).startswith(str(UPLOAD_FOLDER))):
            return jsonify({'error': 'Access denied'}), 403
        
        # Extract text
        text, error = extract_text(str(full_path))
        
        if error:
            return jsonify({'error': error}), 400
        
        full = request.args.get('full') == '1'
        return jsonify({
            'file': full_path.name,
            'path': file_path,
            'size': full_path.stat().st_size,
            'content': text if full else text[:2000],
            'full_length': len(text)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# SINGLE DOCUMENT CLASSIFICATION
# ============================================================================

@app.route('/api/classify', methods=['POST'])
@limiter.limit('30 per hour; 5 per minute')
def api_classify():
    """Classify a single document."""
    try:
        data = request.json or {}
        file_path = sanitize_file_path(data.get('file_path', ''))
        
        if not file_path:
            return jsonify({'error': 'No file path provided'}), 400
        
        # Normalize path separators and construct full path
        file_path = file_path.replace('\\', '/')
        full_path = (project_root / file_path).resolve()
        
        # Resolve allowed base dirs to prevent symlink/traversal bypasses
        allowed_bases = [
            (project_root / 'demo_sharepoint').resolve(),
            UPLOAD_FOLDER.resolve(),
        ]
        
        # Security checks — use resolved paths to block ../ traversal
        if not full_path.exists() or not full_path.is_file():
            return jsonify({'error': 'File not found'}), 404
        
        if not any(str(full_path).startswith(str(base)) for base in allowed_bases):
            return jsonify({'error': 'Access denied'}), 403
        
        # Extract text
        text, error = extract_text(str(full_path))
        if error:
            return jsonify({'error': f'Extraction failed: {error}'}), 400
        
        # Get RAG context
        rag_results = rag_engine.retrieve(text, top_k=3)
        
        # Classify
        classification = classifier.classify(text, full_path.name)
        
        if not classification:
            return jsonify({'error': 'Classification failed'}), 500
        
        # Extract risk metrics
        risk_score = float(classification.get('risk_score', '5'))
        has_pii = len(classification.get('pii_detected', [])) > 0
        sensitivity = classification.get('sensitivity_level', 'Low')
        
        return jsonify({
            'status': 'success',
            'file': full_path.name,
            'classification': classification,
            'rag_context': rag_results,
            'text_preview': text[:1000],
            'risk_assessment': {
                'risk_score': risk_score,
                'has_pii': has_pii,
                'sensitivity': sensitivity,
                'is_high_risk': risk_score >= 7.0 or sensitivity == 'High' or has_pii
            }
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# FILE UPLOAD
# ============================================================================

@app.route('/api/upload', methods=['POST'])
@limiter.limit('20 per hour; 5 per minute')
def api_upload():
    """Upload and classify a new document."""
    try:
        # Check if file in request
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({
                'error': f'File type not allowed. Supported: {", ".join(ALLOWED_EXTENSIONS)}'
            }), 400
        
        # Save file
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
        filename = timestamp + filename
        filepath = UPLOAD_FOLDER / filename
        file.save(str(filepath))
        
        # Extract text
        text, error = extract_text(str(filepath))
        if error:
            return jsonify({'error': f'Extraction failed: {error}'}), 400
        
        # Get RAG context
        rag_results = rag_engine.retrieve(text, top_k=3)
        
        # Classify
        classification = classifier.classify(text, filepath.name)
        
        if not classification:
            return jsonify({'error': 'Classification failed'}), 500
        
        # Extract risk metrics
        risk_score = float(classification.get('risk_score', '5'))
        has_pii = len(classification.get('pii_detected', [])) > 0
        sensitivity = classification.get('sensitivity_level', 'Low')
        
        return jsonify({
            'status': 'success',
            'file': filepath.name,
            'file_path': f'uploads/{filename}',
            'classification': classification,
            'rag_context': rag_results,
            'text_preview': text[:1000],
            'risk_assessment': {
                'risk_score': risk_score,
                'has_pii': has_pii,
                'sensitivity': sensitivity,
                'is_high_risk': risk_score >= 7.0 or sensitivity == 'High' or has_pii
            }
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# SITE SCANNING — MERIDIAN CONSULTING GROUP DEMO
# ============================================================================

# The 3 Meridian consulting firm demo SharePoint sites
MERIDIAN_SITES = {
    "Meridian — Client Engagements": {
        "path": project_root / "demo_sharepoint" / "Meridian_Client_Site",
        "description": "Client contracts, SOWs, proposals, meeting notes & deliverables",
        "icon": "handshake",
        "color": "#3B82F6",
        "url": "https://meridian.sharepoint.com/sites/ClientEngagements",
    },
    "Meridian — Finance & Billing": {
        "path": project_root / "demo_sharepoint" / "Meridian_Finance_Site",
        "description": "Invoices, financial reports, budgets, payroll & vendor contracts",
        "icon": "chart-line",
        "color": "#10B981",
        "url": "https://meridian.sharepoint.com/sites/FinanceBilling",
    },
    "Meridian — People & Culture": {
        "path": project_root / "demo_sharepoint" / "Meridian_HR_Site",
        "description": "Employee records, offer letters, performance reviews & HR policies",
        "icon": "users",
        "color": "#8B5CF6",
        "url": "https://meridian.sharepoint.com/sites/PeopleCulture",
    },
}


def _count_site_docs(site_path: Path) -> int:
    """Count documents in a site directory."""
    if not site_path.exists():
        return 0
    return sum(1 for f in site_path.rglob('*') if f.is_file() and f.suffix.lower() in {'.txt', '.pdf', '.docx'})


def _classify_document_fast(filename: str, content_preview: str = '') -> dict:
    """
    Fast keyword-based document classification for bulk site scanning.
    Returns deterministic classification based on filename and content keywords.
    Does NOT call the Gemini API — used for the site scanner simulation.
    """
    name = filename.lower()
    text = (name + ' ' + content_preview.lower())[:2000]

    # ── Functional Group Detection ─────────────────────────────────────────
    if any(k in text for k in ['payroll', 'salary', 'ssn', 'social security', 'employee record',
                                 'offer letter', 'performance review', 'pip ', 'termination',
                                 'onboard', 'handbook', 'benefits', 'pto ', '401k', '401(k)', 'hr ']):
        group = 'Human Resources'
        base_risk = 7.2
        sensitivity = 'High'
        pii = ['Full Name', 'Social Security Number', 'Date of Birth', 'Home Address',
               'Email Address', 'Bank Account Number']
        findings = [
            'Contains employee personal data including SSN and compensation details',
            'Home addresses and personal contact information present',
            'Financial account details (direct deposit) found',
        ]
        summary = 'Human resources document containing sensitive employee personal information, compensation data, and potentially regulated personal identifiers.'

    elif any(k in text for k in ['invoice', 'billing', 'budget', 'revenue', 'p&l', 'profit',
                                   'payroll register', 'bank account', 'aba ', 'routing number',
                                   'financial performance', 'expense report', 'vendor contract',
                                   'accounts receivable', 'partner comp', 'fee ', 'payment terms']):
        group = 'Finance and Accounting'
        base_risk = 7.8
        sensitivity = 'High'
        pii = ['Bank Account Number', 'Routing Number', 'Tax ID / EIN', 'Credit Card Number']
        findings = [
            'Contains financial account numbers and routing information',
            'Revenue and compensation data present — partner-level salary details',
            'Vendor banking details and payment terms disclosed',
        ]
        summary = 'Financial document containing sensitive account numbers, revenue data, and compensation information subject to strict access controls.'

    elif any(k in text for k in ['nda', 'non-disclosure', 'confidentiality agreement', 'master services',
                                   'statement of work', 'sow', 'legal', 'compliance', 'governing law',
                                   'intellectual property', 'liability', 'termination clause',
                                   'regulatory', 'hipaa', 'gdpr', 'indemnif']):
        group = 'Legal + Compliance'
        base_risk = 6.4
        sensitivity = 'High'
        pii = ['Full Name', 'Email Address', 'Business Address', 'Tax ID / EIN']
        findings = [
            'Contains executed or draft legal agreement with binding obligations',
            'Client/counterparty personal and business contact information',
            'Financial terms, fees, and payment conditions disclosed',
        ]
        summary = 'Legal agreement or compliance document with binding obligations and confidential business terms between Meridian and a counterparty.'

    elif any(k in text for k in ['proposal', 'deliverable', 'client', 'engagement', 'project',
                                   'meeting minutes', 'steering committee', 'milestones', 'msa',
                                   'scope of work', 'advisory', 'consulting services', 'kickoff']):
        group = 'Customer / Client Documentation'
        base_risk = 5.8
        sensitivity = 'Moderate'
        pii = ['Full Name', 'Email Address', 'Phone Number', 'Business Address']
        findings = [
            'Contains client contact information and business relationship details',
            'Engagement fees and commercial terms present',
            'Client strategic information and project details disclosed',
        ]
        summary = 'Client-facing consulting document with engagement details, stakeholder contacts, commercial terms, and project deliverable information.'

    elif any(k in text for k in ['password', 'credential', 'vpn', 'firewall', 'network',
                                   'server', 'admin', 'security policy', 'encryption',
                                   'cyberark', 'crowdstrike', 'breach', 'incident response',
                                   'ip address', 'it policy', 'acceptable use']):
        group = 'IT & Systems'
        base_risk = 6.9
        sensitivity = 'High'
        pii = ['IP Address', 'System Credentials', 'Network Configuration']
        findings = [
            'Contains IT infrastructure details, access control information',
            'Network architecture or credential management references present',
            'Security incident response procedures disclosed — internal use only',
        ]
        summary = 'IT policy or security document containing infrastructure details, access controls, and sensitive system configuration information.'

    else:
        group = 'General Business Operations'
        base_risk = 3.1
        sensitivity = 'Low'
        pii = []
        findings = ['General business document with no identified sensitive content.']
        summary = 'General business document. No high-risk or regulated content identified. Standard internal use classification applies.'

    # ── Deterministic risk score jitter (based on filename hash, stays consistent) ──
    seed = int(hashlib.md5(filename.encode()).hexdigest()[:6], 16)
    jitter = (seed % 20 - 10) / 10.0   # range: -1.0 to +1.0
    raw_score = min(10.0, max(1.0, base_risk + jitter))
    risk_score = round(raw_score * 10) / 10   # 1 decimal

    is_high_risk = risk_score >= 7.0 or sensitivity == 'High'

    return {
        'classification': {
            'functional_group': group,
            'sensitivity_level': sensitivity,
            'risk_score': risk_score,
            'is_high_risk': is_high_risk,
            'pii_detected': pii if pii else [],
            'confidential_findings': findings,
            'document_summary': summary,
        },
        'risk_assessment': {
            'risk_score': risk_score,
            'is_high_risk': is_high_risk,
            'risk_factors': findings[:2],
        }
    }


def _build_scan_report(classified_docs: list, site_name: str = None) -> dict:
    """Build a structured scan report from classified documents."""
    total = len(classified_docs)
    if total == 0:
        return {
            'total_documents_scanned': 0,
            'high_risk_count': 0,
            'high_risk_percentage': '0.0%',
            'pii_detected_count': 0,
            'average_risk_score': 0.0,
            'by_group': {},
            'by_sensitivity': {'High': 0, 'Moderate': 0, 'Low': 0},
            'top_risks': [],
            'risk_summary': {'critical_risk': [], 'high_risk': [], 'medium_risk': [], 'low_risk': []},
            'sensitive_data_alert': {'total_with_pii': 0, 'types_found': []},
            'documents': [],
            'generated_at': datetime.now().isoformat(),
        }

    scores = []
    by_group = {}
    by_sensitivity = {'High': 0, 'Moderate': 0, 'Low': 0}
    pii_docs = []
    pii_types_all = set()
    documents_out = []

    for doc in classified_docs:
        cl = doc.get('classification') or {}
        ra = doc.get('risk_assessment') or {}
        score = float(cl.get('risk_score') or ra.get('risk_score') or 0.0)
        scores.append(score)

        grp = cl.get('functional_group', 'Unknown')
        by_group[grp] = by_group.get(grp, 0) + 1

        sens = cl.get('sensitivity_level', 'Low')
        by_sensitivity[sens] = by_sensitivity.get(sens, 0) + 1

        piis = cl.get('pii_detected', [])
        if piis:
            pii_docs.append(doc)
            pii_types_all.update(piis)

        documents_out.append({
            'name': doc.get('name', ''),
            'path': doc.get('path', ''),
            'site': doc.get('site', site_name or ''),
            'risk_score': score,
            'functional_group': grp,
            'sensitivity_level': sens,
            'pii_detected': piis,
            'is_high_risk': bool(cl.get('is_high_risk') or ra.get('is_high_risk') or score >= 7.0),
            'summary': cl.get('document_summary', ''),
        })

    avg_score = round(sum(scores) / total, 1) if scores else 0.0
    high_risk_docs = [d for d in documents_out if d['risk_score'] >= 7.0]
    critical_docs = [d for d in documents_out if d['risk_score'] >= 8.5]
    med_docs = [d for d in documents_out if 5.0 <= d['risk_score'] < 7.0]
    low_docs = [d for d in documents_out if d['risk_score'] < 5.0]

    sorted_docs = sorted(documents_out, key=lambda x: x['risk_score'], reverse=True)

    return {
        'total_documents_scanned': total,
        'high_risk_count': len(high_risk_docs),
        'high_risk_percentage': f'{len(high_risk_docs)/total*100:.1f}%',
        'pii_detected_count': len(pii_docs),
        'average_risk_score': avg_score,
        'by_group': dict(sorted(by_group.items(), key=lambda x: x[1], reverse=True)),
        'by_sensitivity': by_sensitivity,
        'top_risks': sorted_docs[:10],
        'risk_summary': {
            'critical_risk': [d for d in sorted_docs if d['risk_score'] >= 8.5],
            'high_risk': [d for d in sorted_docs if 7.0 <= d['risk_score'] < 8.5],
            'medium_risk': [d for d in sorted_docs if 5.0 <= d['risk_score'] < 7.0],
            'low_risk': [d for d in sorted_docs if d['risk_score'] < 5.0],
        },
        'sensitive_data_alert': {
            'total_with_pii': len(pii_docs),
            'types_found': sorted(list(pii_types_all)),
        },
        'documents': sorted_docs,
        'generated_at': datetime.now().isoformat(),
    }


@app.route('/api/scan/sites', methods=['GET'])
def api_scan_sites():
    """Get the 3 Meridian consulting firm SharePoint sites with metadata."""
    sites = []
    for name, meta in MERIDIAN_SITES.items():
        path = meta['path']
        doc_count = _count_site_docs(path)
        sites.append({
            'id': name,
            'name': name,
            'description': meta['description'],
            'icon': meta['icon'],
            'color': meta['color'],
            'url': meta['url'],
            'doc_count': doc_count,
            'path': str(path),
            'exists': path.exists(),
        })
    return jsonify(sites)


@app.route('/api/scan/site', methods=['POST'])
@limiter.limit('10 per hour; 3 per minute')
def api_scan_site():
    """
    Scan a specific Meridian SharePoint site.
    Performs fast keyword-based classification of all documents — no AI API call.
    Returns full classified document list and summary report.
    """
    try:
        data = request.json or {}
        site_id = data.get('site_id') or data.get('site')

        if not site_id or site_id not in MERIDIAN_SITES:
            return jsonify({'error': f'Unknown site: {site_id}. Valid sites: {list(MERIDIAN_SITES.keys())}'}), 400

        site_meta = MERIDIAN_SITES[site_id]
        site_path = site_meta['path']

        if not site_path.exists():
            return jsonify({'error': f'Site directory not found: {site_path}'}), 404

        classified_docs = []
        for file_path in sorted(site_path.rglob('*')):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in {'.txt', '.pdf', '.docx'}:
                continue
            if file_path.name.startswith('.'):
                continue

            # Read a small preview of text content (for .txt files)
            preview = ''
            try:
                if file_path.suffix.lower() == '.txt':
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        preview = f.read(800)
            except Exception:
                pass

            cl_result = _classify_document_fast(file_path.name, preview)
            stat = file_path.stat()

            classified_docs.append({
                'name': file_path.name,
                'path': str(file_path.relative_to(project_root)).replace('\\', '/'),
                'site': site_id,
                'size_bytes': stat.st_size,
                'size_mb': round(stat.st_size / (1024 * 1024), 3),
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'extension': file_path.suffix.lower(),
                'classification': cl_result['classification'],
                'risk_assessment': cl_result['risk_assessment'],
                'status': 'classified',
            })

        report = _build_scan_report(classified_docs, site_id)
        return jsonify({
            'status': 'success',
            'site': site_id,
            'site_meta': {
                'description': site_meta['description'],
                'icon': site_meta['icon'],
                'color': site_meta['color'],
                'url': site_meta['url'],
            },
            'report': report,
            'documents': classified_docs,
        })

    except Exception as e:
        logger.exception('Error scanning site')
        return jsonify({'error': str(e)}), 500


@app.route('/api/scan/all', methods=['POST'])
def api_scan_all():
    """Scan all 3 Meridian SharePoint sites and return combined report."""
    try:
        all_classified = []
        site_reports = {}

        for site_id, site_meta in MERIDIAN_SITES.items():
            site_path = site_meta['path']
            if not site_path.exists():
                continue

            site_docs = []
            for file_path in sorted(site_path.rglob('*')):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in {'.txt', '.pdf', '.docx'}:
                    continue
                if file_path.name.startswith('.'):
                    continue

                preview = ''
                try:
                    if file_path.suffix.lower() == '.txt':
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            preview = f.read(800)
                except Exception:
                    pass

                cl_result = _classify_document_fast(file_path.name, preview)
                stat = file_path.stat()
                doc = {
                    'name': file_path.name,
                    'path': str(file_path.relative_to(project_root)).replace('\\', '/'),
                    'site': site_id,
                    'size_bytes': stat.st_size,
                    'size_mb': round(stat.st_size / (1024 * 1024), 3),
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    'extension': file_path.suffix.lower(),
                    'classification': cl_result['classification'],
                    'risk_assessment': cl_result['risk_assessment'],
                    'status': 'classified',
                }
                site_docs.append(doc)
                all_classified.append(doc)

            site_reports[site_id] = _build_scan_report(site_docs, site_id)

        combined_report = _build_scan_report(all_classified)
        combined_report['by_site'] = {
            sid: {
                'total': sr['total_documents_scanned'],
                'high_risk': sr['high_risk_count'],
                'avg_risk': sr['average_risk_score'],
                'pii_count': sr['pii_detected_count'],
            }
            for sid, sr in site_reports.items()
        }

        return jsonify({
            'status': 'success',
            'report': combined_report,
            'documents': all_classified,
            'site_reports': site_reports,
        })

    except Exception as e:
        logger.exception('Error in scan all')
        return jsonify({'error': str(e)}), 500


@app.route('/api/scan/status')
def api_scan_status():
    """Get current scan status."""
    total = sum(_count_site_docs(m['path']) for m in MERIDIAN_SITES.values())
    return jsonify({
        'status': 'ready',
        'sites': len(MERIDIAN_SITES),
        'total_documents': total,
    })


# ============================================================================
# AI INSIGHTS
# ============================================================================

def _generate_local_insights(site_id, total, avg, high_r, pii_cnt,
                              by_sens, by_group, top_docs, pii_types):
    """Rule-based insights generator used as fallback when Gemini API is unavailable."""
    high_s  = by_sens.get('High', 0)
    mod_s   = by_sens.get('Moderate', 0)
    low_s   = by_sens.get('Low', 0)
    high_pct = round(high_s / total * 100) if total else 0
    pii_pct  = round(pii_cnt / total * 100) if total else 0

    # Risk level label
    if avg >= 7.5:
        risk_level = 'critical'
    elif avg >= 5.5:
        risk_level = 'elevated'
    elif avg >= 3.5:
        risk_level = 'moderate'
    else:
        risk_level = 'low'

    # Executive summary
    top_doc_names = ', '.join(d['name'] for d in top_docs[:2]) if top_docs else 'none identified'
    exec_summary = (
        f"{site_id} contains {total} document(s) with an average risk score of {avg:.1f}/10, "
        f"indicating {risk_level} overall exposure. "
        f"{high_s} document(s) ({high_pct}%) are classified as High sensitivity"
        f"{f', with {pii_cnt} containing personally identifiable information ({pii_pct}%)' if pii_cnt else ''}. "
        f"Highest-risk items include: {top_doc_names}."
    )

    # Compliance posture
    if high_r >= 3 or pii_cnt >= 3:
        compliance = (
            f"Compliance posture is compromised. {high_r} high-risk document(s) and "
            f"{pii_cnt} PII-containing file(s) require immediate access controls and policy review."
        )
    elif high_r >= 1 or pii_cnt >= 1:
        compliance = (
            f"Compliance posture is partially adequate but requires attention. "
            f"{high_r} high-risk document(s) and {pii_cnt} PII-containing file(s) "
            f"should be reviewed and protected under applicable data governance policies."
        )
    else:
        compliance = (
            f"Compliance posture appears satisfactory based on current classifications. "
            f"No high-risk documents or PII detected. Continue monitoring for future uploads."
        )

    # Top actions
    actions = []
    if high_r > 0:
        actions.append(
            f"Immediately restrict access to {high_r} High-sensitivity document(s) and apply "
            f"need-to-know permissions — these represent the greatest breach risk."
        )
    if pii_cnt > 0:
        pii_label = ', '.join(pii_types[:3]) if pii_types else 'personal data'
        actions.append(
            f"Audit {pii_cnt} document(s) containing PII ({pii_label}) for compliance with "
            f"GDPR/CCPA data minimisation and retention requirements."
        )
    if mod_s > 0:
        actions.append(
            f"Review {mod_s} Moderate-sensitivity document(s) to confirm classifications are accurate "
            f"and apply appropriate labeling and access controls."
        )
    if not actions:
        actions.append("Maintain current classification policies and schedule periodic re-scans.")
    if len(actions) < 3:
        actions.append(
            "Implement a data governance policy requiring sensitivity labeling on all new documents at creation time."
        )
    if len(actions) < 3:
        actions.append(
            "Conduct staff awareness training on proper handling of sensitive and PII-containing documents."
        )

    # Regulatory exposure
    pii_lower = [p.lower() for p in pii_types]
    has_personal = any(k in ' '.join(pii_lower) for k in ['name','email','phone','address','ssn','dob','birth'])
    has_health   = any(k in ' '.join(pii_lower) for k in ['health','medical','hipaa','patient','diagnosis'])
    has_financial = any(k in ' '.join(pii_lower) for k in ['financial','bank','account','wire','payroll','tax','revenue'])
    top_groups = list(by_group.keys())

    gdpr  = (f"Elevated — {pii_cnt} document(s) contain personal data subject to GDPR Article 5 storage limitation and Article 32 security requirements."
             if has_personal or pii_cnt > 0 else "No significant exposure detected.")
    ccpa  = (f"Potential exposure — personal information present that may be subject to CCPA consumer rights obligations."
             if has_personal else "No significant exposure detected.")
    hipaa = (f"Elevated — health/medical data detected. HIPAA Security Rule safeguards and BAA requirements apply."
             if has_health else "No significant exposure detected.")
    sox   = (f"Potential exposure — financial records present requiring SOX audit trail and access control compliance."
             if has_financial or any('finance' in g.lower() for g in top_groups) else "No significant exposure detected.")

    # Governance recommendations
    governance = [
        f"Apply sensitivity labels to all {total} document(s) and enforce label-based access control policies.",
        f"Establish a document retention schedule — High-sensitivity files should have defined expiry dates.",
        f"Enable audit logging on all document access and modification events for compliance traceability.",
        f"Restrict external sharing of {high_s + mod_s} High/Moderate-sensitivity document(s) to approved personnel only.",
        f"Schedule quarterly re-scans to detect newly added sensitive content across all site libraries.",
    ]

    # Risk narrative
    if risk_level in ('critical', 'elevated'):
        risk_narrative = (
            f"The current risk trajectory is concerning. With {high_r} high-risk document(s) and an average score "
            f"of {avg:.1f}/10, unaddressed exposure could lead to regulatory penalties, data breach liability, "
            f"and reputational harm. Immediate remediation of the highest-scoring items is strongly recommended."
        )
    else:
        risk_narrative = (
            f"The current risk trajectory is manageable. The average score of {avg:.1f}/10 suggests baseline "
            f"controls are in place, but ongoing classification hygiene and access reviews are essential "
            f"to prevent risk from increasing as the document library grows."
        )

    return {
        'status': 'success',
        'site_id': site_id,
        'executive_summary': exec_summary,
        'compliance_posture': compliance,
        'top_actions': actions[:3],
        'regulatory_exposure': {'gdpr': gdpr, 'ccpa': ccpa, 'hipaa': hipaa, 'sox': sox},
        'data_governance': governance[:5],
        'risk_narrative': risk_narrative,
        'raw': '(Generated locally — Gemini API quota temporarily exhausted)',
    }


@app.route('/api/test/ai', methods=['GET'])
def test_ai_connection():
    """Quick test endpoint to verify AI connectivity."""
    try:
        classifier._get_client() 
        start_time = time.time()
        
        # Simple test prompt
        response = classifier._client.models.generate_content(
            model=classifier.model, 
            contents="Say 'AI connection working' in exactly those words."
        )
        
        elapsed = time.time() - start_time
        logger.info(f"AI test completed in {elapsed:.2f} seconds")
        
        return jsonify({
            'status': 'success',
            'response': response.text,
            'model': classifier.model,
            'time_taken': elapsed
        })
    except Exception as e:
        logger.error(f"AI test failed: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/scan/ai_insights', methods=['POST'])
def api_scan_ai_insights():
    """Generate Gemini-powered narrative insights for a completed scan report."""
    import time
    start_time = time.time()
    _raw_sid = (request.json or {}).get('site_id', 'All Sites') if request.json else 'Unknown'
    logger.info(f"Starting AI insights generation for site: {sanitize_str(_raw_sid, 100)}")
    
    try:
        data = request.json or {}
        site_id = sanitize_str(data.get('site_id', 'All Sites'), 200)
        report = data.get('report', {})
        logger.info(f"Processing report with {report.get('total_documents_scanned', 0)} documents")

        avg      = float(report.get('average_risk_score', 0))
        total    = report.get('total_documents_scanned', 0)
        high_r   = report.get('high_risk_count', 0)
        pii_cnt  = report.get('pii_detected_count', 0)
        by_sens  = report.get('by_sensitivity', {})
        by_group = report.get('by_group', {})
        top_docs = report.get('top_risks', [])[:5]
        pii_types = report.get('sensitive_data_alert', {}).get('types_found', [])

        docs_summary = '\n'.join([
            f"  - {d['name']}: risk={float(d.get('risk_score',0)):.1f}, "
            f"sensitivity={d.get('sensitivity_level','?')}, pii={d.get('pii_detected','N/A')}"
            for d in top_docs
        ])

        prompt = f"""You are a data governance and compliance expert analyzing a SharePoint document scan for Meridian Consulting Group.

SCAN RESULTS FOR: {site_id}
- Total documents scanned: {total}
- Average risk score: {avg:.1f}/10
- High risk documents (score >= 7.0): {high_r}
- Documents containing PII: {pii_cnt}
- Sensitivity breakdown: High={by_sens.get('High',0)}, Moderate={by_sens.get('Moderate',0)}, Low={by_sens.get('Low',0)}
- Document categories: {json.dumps(by_group)}
- PII types detected: {', '.join(pii_types) if pii_types else 'None'}
- Highest risk documents:
{docs_summary}

Provide a structured analysis with these exact section headers. Be specific and actionable:

EXECUTIVE_SUMMARY: [2-3 sentences summarizing the overall security posture and key risk]

COMPLIANCE_POSTURE: [1-2 sentences assessing current compliance stance]

TOP_ACTIONS:
1. [Most urgent action with specific rationale]
2. [Second priority action]
3. [Third priority action]

REGULATORY_EXPOSURE:
GDPR: [specific exposure or "No significant exposure"]
CCPA: [specific exposure or "No significant exposure"]
HIPAA: [specific exposure or "No significant exposure"]
SOX: [specific exposure or "No significant exposure"]

DATA_GOVERNANCE:
- [Recommendation 1]
- [Recommendation 2]
- [Recommendation 3]

RISK_NARRATIVE: [2-3 sentences about risk trajectory and consequences if unaddressed]"""

        import threading
        from google import genai as genai_module

        api_keys = [
            k for k in [
                os.getenv('GEMINI_API_KEY'),
                os.getenv('GEMINI_API_KEY_2'),
            ] if k
        ]
        models_to_try = [
            classifier.model,
            'gemini-2.0-flash-lite',
            'gemini-1.5-flash',
            'gemini-1.5-flash-8b',
        ]
        raw = None
        last_err = None

        def _try_generate(client, model_name, prompt_text):
            """Attempt a generate_content call; return (text, error)."""
            result = [None]
            err    = [None]
            def _call():
                try:
                    r = client.models.generate_content(model=model_name, contents=prompt_text)
                    result[0] = r.text if r else None
                except Exception as exc:
                    err[0] = exc
            t = threading.Thread(target=_call, daemon=True)
            t.start(); t.join(timeout=60)
            if t.is_alive():
                return None, TimeoutError(f"{model_name} timed out")
            return result[0], err[0]

        for key_idx, api_key in enumerate(api_keys):
            try:
                client = genai_module.Client(api_key=api_key)
            except Exception as e:
                logger.error(f"Key {key_idx+1} client init failed: {e}")
                continue
            logger.info(f"Trying API key {key_idx+1}/{len(api_keys)}")
            for i, model_name in enumerate(models_to_try):
                model_start = time.time()
                logger.info(f"  Model {i+1}/{len(models_to_try)}: {model_name}")
                text, err = _try_generate(client, model_name, prompt)
                elapsed = time.time() - model_start
                if err is not None:
                    err_str = str(err)
                    logger.error(f"  {model_name} failed in {elapsed:.2f}s: {err_str[:120]}")
                    if ('429' in err_str or 'RESOURCE_EXHAUSTED' in err_str
                            or '404' in err_str or 'NOT_FOUND' in err_str
                            or '503' in err_str or 'UNAVAILABLE' in err_str
                            or 'high demand' in err_str):
                        last_err = err
                        continue
                    raise err
                if text:
                    raw = text
                    logger.info(f"  {model_name} succeeded in {elapsed:.2f}s (key {key_idx+1})")
                    break
                logger.warning(f"  {model_name} returned empty response")
            if raw:
                break  # one key succeeded — stop trying more keys

        if raw is None:
            logger.warning("All API keys and models exhausted — using rule-based local fallback")
            fallback = _generate_local_insights(
                site_id=site_id, total=total, avg=avg, high_r=high_r,
                pii_cnt=pii_cnt, by_sens=by_sens, by_group=by_group,
                top_docs=top_docs, pii_types=pii_types
            )
            fallback['fallback'] = True
            return jsonify(fallback)

        logger.info(f"Raw response received, length: {len(raw)} characters")
        parsing_start = time.time()

        def extract_section(text, label, end_labels):
            pattern = rf'{label}:\s*(.*?)(?=(?:{"|".join(end_labels)}):|\Z)'
            m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            return m.group(1).strip() if m else ''

        exec_summary = extract_section(raw, 'EXECUTIVE_SUMMARY',
                                       ['COMPLIANCE_POSTURE', 'TOP_ACTIONS', 'REGULATORY_EXPOSURE'])
        compliance   = extract_section(raw, 'COMPLIANCE_POSTURE',
                                       ['TOP_ACTIONS', 'REGULATORY_EXPOSURE', 'DATA_GOVERNANCE'])
        risk_narr    = extract_section(raw, 'RISK_NARRATIVE', ['APPENDIX', r'\Z'])

        actions_block = extract_section(raw, 'TOP_ACTIONS',
                                        ['REGULATORY_EXPOSURE', 'DATA_GOVERNANCE', 'RISK_NARRATIVE'])
        actions = [
            re.sub(r'^[\d.\-)\s]+', '', line).strip()
            for line in actions_block.split('\n')
            if line.strip() and line.strip()[0].isdigit()
        ][:3]

        reg_block = extract_section(raw, 'REGULATORY_EXPOSURE',
                                    ['DATA_GOVERNANCE', 'RISK_NARRATIVE'])
        def parse_reg(block, key):
            m = re.search(rf'{key}:\s*(.+?)(?:\n|$)', block, re.IGNORECASE)
            return m.group(1).strip() if m else 'Not assessed'

        gov_block = extract_section(raw, 'DATA_GOVERNANCE', ['RISK_NARRATIVE'])
        governance = [
            re.sub(r'^[-\u2022\s]+', '', line).strip()
            for line in gov_block.split('\n')
            if line.strip() and (line.strip().startswith('-') or line.strip().startswith('\u2022'))
        ][:5]

        parsing_time = time.time() - parsing_start
        total_time = time.time() - start_time
        logger.info(f"AI insights generation completed successfully in {total_time:.2f} seconds (parsing: {parsing_time:.2f}s)")

        return jsonify({
            'status': 'success',
            'site_id': site_id,
            'executive_summary': exec_summary,
            'compliance_posture': compliance,
            'top_actions': actions,
            'regulatory_exposure': {
                'gdpr':  parse_reg(reg_block, 'GDPR'),
                'ccpa':  parse_reg(reg_block, 'CCPA'),
                'hipaa': parse_reg(reg_block, 'HIPAA'),
                'sox':   parse_reg(reg_block, 'SOX'),
            },
            'data_governance': governance,
            'risk_narrative': risk_narr,
            'raw': raw,
        })
    except Exception as e:
        total_time = time.time() - start_time
        err_str = str(e)
        logger.exception(f'Error generating AI insights after {total_time:.2f} seconds: {err_str}')
        if '503' in err_str or 'UNAVAILABLE' in err_str or 'high demand' in err_str:
            return jsonify({'error': 'unavailable', 'message': 'The AI model is temporarily experiencing high demand. Please try again shortly.'}), 503
        return jsonify({'error': err_str}), 500


# ============================================================================
# RESULTS EXPORT
# ============================================================================

@app.route('/api/export/json')
def api_export_json():
    """Export current scan results as JSON."""
    if not scanner.results:
        return jsonify({'error': 'No scan results available'}), 400
    
    report = scanner._generate_risk_report({}, verbose=False)
    
    # Add detailed results
    report['detailed_results'] = []
    for result in scanner.results:
        report['detailed_results'].append({
            'file_name': result['file_name'],
            'functional_group': result['classification'].get('functional_group'),
            'sensitivity': result['classification'].get('sensitivity_level'),
            'risk_score': result['classification'].get('risk_score'),
            'pii_detected': result['classification'].get('pii_detected', []),
            'sensitive_data': result['classification'].get('sensitive_data_types', [])
        })
    
    # Save to reports folder
    filename = f"risk_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = REPORTS_FOLDER / filename
    
    with open(filepath, 'w') as f:
        json.dump(report, f, indent=2)
    
    return send_file(str(filepath), as_attachment=True)


@app.route('/api/verify', methods=['POST'])
def api_verify_classification():
    """Store human verification/correction of AI classification."""
    try:
        data = request.json or {}
        file_path = sanitize_file_path(data.get('file_path', ''))
        action = sanitize_str(data.get('action', ''), 20).lower()
        corrections = data.get('corrections', {})
        reason = sanitize_str(data.get('reason', ''), 1000)
        
        if not file_path or not action:
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Validate action against allowlist to prevent injection via stored data
        if action not in _VERIFY_ACTIONS:
            return jsonify({'error': f'Invalid action. Must be one of: {sorted(_VERIFY_ACTIONS)}'}), 400
        
        # Sanitize corrections dict — only allow known string/list values
        if not isinstance(corrections, dict):
            corrections = {}
        corrections = {sanitize_str(k, 100): sanitize_str(v, 500) if isinstance(v, str) else v
                       for k, v in list(corrections.items())[:20]}
        
        # Create verification record
        verification = {
            'file_path': file_path,
            'action': action,
            'timestamp': datetime.now().isoformat(),
            'corrections': corrections,
            'reason': reason,
            'reviewer': 'Human Reviewer'
        }
        
        # Store in verification log
        verification_file = REPORTS_FOLDER / 'human_verifications.json'
        
        if verification_file.exists():
            with open(verification_file, 'r') as f:
                verifications = json.load(f)
        else:
            verifications = []
        
        verifications.append(verification)
        
        with open(verification_file, 'w') as f:
            json.dump(verifications, f, indent=2)
        
        return jsonify({
            'status': 'success',
            'message': f'Verification recorded: {action}',
            'verification_id': len(verifications)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# UTILITY ROUTES
# ============================================================================

def get_site_icon(site_name: str) -> str:
    """Get icon for site type."""
    icons = {
        'Client Site': 'folder-customer',
        'Finance Site': 'folder-finance',
        'HR Site': 'folder-hr',
        'IT Site': 'folder-it',
        'Legal Site': 'folder-legal',
        'Operations Site': 'folder-operations',
    }
    return icons.get(site_name, 'folder')


@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({
        'error': 'Too many requests. Please wait before trying again.',
        'retry_after': str(e.description)
    }), 429


if __name__ == '__main__':
    print("\n" + "=" * 80)
    print("UNIFIED DOCUMENT CLASSIFICATION INTERFACE")
    print("=" * 80)
    print("\n Web Interface: http://localhost:5000")
    print(" Upload Folder: " + str(UPLOAD_FOLDER))
    print(" Documents Folder: " + str(project_root / 'demo_sharepoint'))
    print("\n[OK] RAG Engine initialized")
    print("[OK] AI Classifier ready")
    print("[OK] SharePoint Scanner configured")
    print("\n" + "=" * 80 + "\n")
    
    # Use environment variable for debug mode
    debug_mode = os.getenv('FLASK_DEBUG', '0') == '1'
    port = int(os.getenv('PORT', 5000))   # Railway injects PORT; local default is 5000
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
