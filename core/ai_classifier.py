"""
AI Classifier Module

Calls Gemini API to classify documents into functional groups and sensitivity levels.
Handles API communication, retries, and error handling.

Input: Document content + embeddings + metadata
Output: Functional group, sensitivity level, confidence, reasoning
"""

import logging
import json
import re
import time
from typing import Dict, Optional
import os

logger = logging.getLogger(__name__)


class AIClassifier:
    """
    Classifies documents using Google Gemini API.
    """

    FUNCTIONAL_GROUPS = [
        'HR',
        'Finance and Accounting',
        'Legal + Compliance',
        'Customer / Client Documentation',
        'Sales & Business Development',
        'Marketing & Communications',
        'IT & Systems',
        'Product Development / R&D',
        'Operations and Internal Documentation',
        'Outliers / Others',
    ]

    SENSITIVITY_LEVELS = ['Low', 'Moderate', 'High']

    def __init__(self, api_key: str = None, model: str = None):
        """
        Initialize Gemini API classifier.

        Args:
            api_key: Google Gemini API key (or env var GEMINI_API_KEY)
            model: Model name (reads GEMINI_MODEL env var, defaults to gemini-2.0-flash)
        """
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        self.model = model or os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
        self._client = None
        self.max_retries = 3
        self.retry_delay = 2  # seconds

        # Groq fallback (used when Gemini quota is exhausted)
        self.groq_api_key = os.getenv('GROQ_API_KEY')
        self.groq_model = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')

        # Local Ollama fallback (used when Gemini quota is exhausted)
        self.ollama_url = os.getenv('OLLAMA_URL', 'http://localhost:11434')
        self.ollama_model = os.getenv('OLLAMA_MODEL', 'llama3.2')

        if not self.api_key:
            logger.warning("GEMINI_API_KEY not set. Classifier will use fallback mode.")
        logger.info(f"AIClassifier using model: {self.model}")

    def _get_client(self):
        """Lazy-load Gemini API client."""
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
                logger.info(f"Gemini client initialized with model: {self.model}")
            except ImportError:
                raise ImportError("google-genai required: pip install google-genai")

    def classify(
        self,
        content: str,
        file_name: str,
        file_size: int = None,
        embedding_confidence: float = None
    ) -> Dict:
        """
        Classify document using Gemini API.

        Args:
            content: Extracted document content (text)
            file_name: Document filename
            file_size: File size in bytes (optional)
            embedding_confidence: Embedding confidence (optional)

        Returns:
            Dict containing:
            - functional_group: Classified category
            - sensitivity_level: Low/Moderate/High
            - confidence: 0.0-1.0 confidence score
            - reasoning: Brief explanation
            - classification_status: 'success', 'api_error', 'parse_error', 'fallback'
            - error_message: Error details if applicable
        """
        if not content or not content.strip():
            logger.warning("Empty content for classification")
            return self._fallback_classification(file_name)

        # Pre-analyse content for PII hits and domain signals before calling the API
        pre_analysis = self._pre_analyze(content, file_name)

        # Build prompt with pre-analysis cheat-sheet embedded
        prompt = self._build_prompt(content, file_name, file_size, pre_analysis)

        # Try API call with retries
        for attempt in range(self.max_retries):
            try:
                if not self.api_key:
                    logger.info("No API key - using fallback classification")
                    return self._fallback_classification(file_name, content)

                self._get_client()
                response = self._client.models.generate_content(
                    model=self.model, contents=prompt
                )

                # Parse and post-validate response
                result = self._parse_response(response.text)
                result = self._post_validate(result, pre_analysis)
                result['classification_status'] = 'success'
                result['model_used'] = f'gemini/{self.model}'
                return result

            except Exception as e:
                error_str = str(e)
                logger.error(f"Attempt {attempt + 1} failed: {error_str}")

                # On quota/rate-limit error skip remaining retries and go to Groq fallback
                if self._is_quota_error(e):
                    logger.warning("Gemini quota/rate-limit reached — trying Groq fallback")
                    return self._classify_with_groq(prompt, pre_analysis, file_name, content)

                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"All retries exhausted for {file_name}")
                    return self._classify_with_groq(prompt, pre_analysis, file_name, content)

    def _pre_analyze(self, content: str, file_name: str) -> dict:
        """Run fast regex + keyword scan BEFORE calling the LLM.
        Returns a dict that is injected into the prompt and used for post-validation."""
        import re
        c = content  # original case
        cl = content.lower()
        fn = file_name.lower()
        findings = []
        pii_hits = []           # ALL signals combined (for backward compat / UI display)
        high_risk_pii = []     # Only genuinely sensitive PII (forces High sensitivity)
        contextual_signals = []  # Informational context — NOT automatic High
        domain_scores = {g: 0 for g in self.FUNCTIONAL_GROUPS if g != 'Outliers / Others'}

        # ── PII scanners (extract actual values where possible) ──────────────
        def _find(pattern, label, sample_fmt=None, flags=0, is_high_risk=False):
            matches = list(re.finditer(pattern, c, flags))
            if matches:
                samples = [m.group(0)[:40] for m in matches[:3]]
                entry = label + (f": {', '.join(samples)}" if sample_fmt else f" ({len(matches)} match{'es' if len(matches)>1 else ''})")
                pii_hits.append(entry)
                findings.append(entry)
                if is_high_risk:
                    high_risk_pii.append(entry)
                else:
                    contextual_signals.append(entry)
                return len(matches)
            return 0

        _find(r'\b\d{3}-\d{2}-\d{4}\b', 'SSN', sample_fmt=True, is_high_risk=True)
        _find(r'\b(?:4[0-9]{3}|5[1-5][0-9]{2}|3[47][0-9]{2})[\s-]?\d{4}[\s-]?\d{4}[\s-]?(?:\d{3,4})\b', 'Credit Card', sample_fmt=True, is_high_risk=True)
        _find(r'\b(?:[Rr]outing|ABA|RTN)[\s:=]+\d{9}\b', 'Routing Number', sample_fmt=True, is_high_risk=True)
        _find(r'\b[A-Z]{6}[A-Z2-9][A-NP-Z0-9]([A-Z0-9]{3})?\b', 'SWIFT/BIC Code', sample_fmt=True, is_high_risk=True)
        _find(r'\b(?:[Aa]ccount|[Aa]cct)\.?\s*(?:#|[Nn]o\.?|[Nn]um(?:ber)?)?\s*[:=]?\s*\d{6,17}\b', 'Bank Account', sample_fmt=True, is_high_risk=True)
        _find(r'\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7,}\b', 'IBAN', sample_fmt=True, is_high_risk=True)
        _find(r'\b[Ww]ire\s+[Tt]ransfer\b', 'Wire Transfer Instructions', is_high_risk=True)
        _find(r'\b(?:password|passwd|pwd)\s*[:=]\s*\S{4,}', 'Password/Credential', sample_fmt=False, flags=re.IGNORECASE, is_high_risk=True)
        _find(r'\bapi[_\-]?key\s*[:=]\s*[A-Za-z0-9_\-]{16,}', 'API Key', sample_fmt=False, flags=re.IGNORECASE, is_high_risk=True)
        _find(r'\bsecret[_\-]?(?:key|token)\s*[:=]\s*\S{10,}', 'Secret Key', sample_fmt=False, flags=re.IGNORECASE, is_high_risk=True)
        _find(r'\b(?:salary|compensation|payroll|base\s+pay)\s*[:=]?\s*\$?[\d,]+', 'Salary/Compensation', sample_fmt=True, flags=re.IGNORECASE, is_high_risk=True)
        _find(r'\b(?:[Mm]edical|[Hh]ealth|HIPAA|PHI|patient\s+(?:ID|record))', 'Medical/Health Data', is_high_risk=True)
        _find(r'\bDOB\b|\b[Dd]ate\s+of\s+[Bb]irth\s*[:=]?\s*\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}', 'Date of Birth', sample_fmt=True, is_high_risk=True)
        # ── Contextual signals — informational only, NOT automatic High ──────
        _find(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b', 'Email Address', sample_fmt=True, is_high_risk=False)
        _find(r'\b\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b', 'Phone Number', sample_fmt=True, is_high_risk=False)
        _find(r'\bEMP[-\s#]?\d{3,}|\b[Ee]mployee\s*(?:ID|#|No\.?)\s*[:=]?\s*[\w\d\-]+', 'Employee ID', sample_fmt=True, is_high_risk=False)
        _find(r'\b\$[\d,]{4,}(?:\.\d{2})?\b', 'Dollar Amount', sample_fmt=True, is_high_risk=False)
        _find(r'\b(?:GDPR|CCPA|PCI[\-\s]DSS|SOX|HIPAA)\b', 'Regulatory Framework', is_high_risk=False)

        # ── Domain keyword scoring ────────────────────────────────────────────
        kw_map = {
            'HR': [
                'employee', 'payroll', 'salary', 'compensation', 'benefits', 'performance review',
                'recruiting', 'onboarding', 'headcount', 'workforce', 'talent', 'hr policy',
                'human capital', 'disciplinary', 'termination', 'background check', 'pip',
                'leave of absence', 'pto', 'paid time off', 'fmla', 'hiring', 'job description',
                'interview', 'offer letter', 'severance', 'bonus', 'equity compensation',
                'stock option', '401k', 'health insurance', 'dental', 'vision', 'overtime',
                'timekeeping', 'org chart', 'succession planning', 'exit interview', 'attrition',
                'retention', 'performance improvement plan', 'corrective action', 'written warning',
                'involuntary termination', 'resignation', 'background screening', 'drug test',
                'w-2', '1099', 'benefits enrollment', 'cobra', 'fsa', 'hsa',
                'workers compensation', 'disability', 'parental leave', 'pay band', 'job grade',
                'staffing', 'contractor', 'hr investigation', 'harassment', 'equal opportunity',
                'diversity', 'inclusion', 'i-9', 'w-4', 'remote work policy', 'hybrid policy',
                'medical leave', 'accommodation', 'reimbursement', 'direct deposit',
                'employee handbook', 'code of conduct', 'learning and development',
            ],
            'Finance and Accounting': [
                'ebitda', 'balance sheet', 'general ledger', 'accounts payable', 'accounts receivable',
                'journal entry', 'tax filing', 'fiscal year', 'cash flow', 'budget variance',
                'income statement', 'revenue recognition', 'audit schedule', 'amortization', 'depreciation',
                'gross margin', 'net income', 'operating income', 'profit and loss', 'p&l',
                'working capital', 'capex', 'opex', 'chart of accounts', 'cost center', 'gl code',
                'trial balance', 'bank reconciliation', 'expense report', 'accrual', 'deferred revenue',
                'accounts receivable aging', 'invoice', 'purchase order', 'payment terms', 'ach payment',
                'tax provision', 'deferred tax', 'tax return', 'gaap', 'ifrs', 'sox compliance',
                'internal controls', 'financial close', 'month-end close', 'year-end close',
                'transfer pricing', 'goodwill', 'impairment', 'write-off', 'bad debt', 'credit memo',
                'treasury', 'liquidity', 'line of credit', 'interest expense', 'budget forecast',
                'financial statement', 'quarterly report', 'annual report', 'tax strategy',
                'variance analysis', 'margin analysis', 'financial model', 'cost allocation',
                'operating expense', 'capital expenditure', 'depreciation schedule', 'financial audit',
                'profit margin', 'revenue forecast', 'audit finding',
            ],
            'Legal + Compliance': [
                'whereas', 'indemnification', 'governing law', 'jurisdiction', 'litigation',
                'settlement', 'nda', 'gdpr', 'sox', 'hipaa', 'pci-dss', 'pci dss', 'arbitration',
                'force majeure', 'data processing agreement', 'regulatory filing', 'contractual',
                'breach of contract', 'intellectual property', 'copyright', 'trademark', 'patent',
                'license agreement', 'service agreement', 'master services agreement', 'msa',
                'statement of work', 'sow', 'liability', 'limitation of liability',
                'warranty disclaimer', 'confidentiality', 'non-compete', 'non-solicitation',
                'injunctive relief', 'termination clause', 'dispute resolution', 'data privacy',
                'right to erasure', 'privacy policy', 'terms of service', 'acceptable use policy',
                'corporate governance', 'board resolution', 'shareholder agreement', 'due diligence',
                'data breach', 'consent order', 'cease and desist', 'employment law',
                'subpoena', 'deposition', 'legal hold', 'e-discovery', 'compliance violation',
                'regulatory risk', 'regulatory requirement', 'representations and warranties',
                'in witness whereof', 'executed as of', 'indemnify', 'obligor', 'addendum',
                'contract amendment', 'exhibit', 'schedule',
            ],
            'IT & Systems': [
                'cloud', 'aws', 'amazon web services', 'azure', 'microsoft azure', 'gcp', 'google cloud',
                'kubernetes', 'k8s', 'docker', 'terraform', 'infrastructure', 'api gateway', 'devops',
                'ci/cd', 'cicd', 'firewall', 'vpn', 'encryption', 'ssl', 'tls', 'subnet', 'ip address',
                'cidr', 'dns', 'active directory', 'ldap', 'iam', 'siem', 'digital transformation',
                'digital maturity', 'cloud migration', 'microservice', 'microservices', 'access control',
                'server', 'database server', 'load balancer', 'ssh', 'ssh key', 'api key', 'api keys',
                'access token', 'bearer token', 'oauth', 'saml', 'mfa', 'multi-factor',
                'zero trust', 'zero-trust', 'network topology', 'penetration test', 'vulnerability',
                'patch management', 'incident response', 'endpoint protection', 'edr',
                'cloud native', 'serverless', 'lambda', 'ec2', 's3 bucket', 'azure devops',
                'github actions', 'jenkins', 'ansible', 'rest api', 'graphql', 'webhook',
                'container registry', 'helm chart', 'reverse proxy', 'nginx', 'apache',
                'tcp/ip', 'vlan', 'wan', 'sd-wan', 'pki', 'certificate authority', 'ssl certificate',
                'ipsec', 'radius', 'snmp', 'syslog', 'intrusion detection', 'ids', 'ips', 'waf',
                'ddos', 'backup recovery', 'disaster recovery', 'rto', 'rpo', 'data center',
                'hypervisor', 'vmware', 'hyper-v', 'data lake', 'data warehouse', 'etl',
                'sql server', 'postgresql', 'mysql', 'mongodb', 'redis', 'elasticsearch',
                'passcode', 'building security', 'access badge', 'network plan', 'system architecture',
                'technical spec', 'cloud config', 'infrastructure config', 'credential store', 'vault',
                'service account', 'private key', 'public key', 'secret', 'port', 'hostname',
            ],
            'Sales & Business Development': [
                'pipeline', 'deal stage', 'win probability', 'quota', 'go-to-market', 'crm',
                'opportunity tracking', 'revenue forecast', 'prospect', 'close rate', 'lead generation',
                'sales cycle', 'discovery call', 'demo', 'proposal', 'rfp', 'rfq',
                'request for proposal', 'sales territory', 'account executive', 'business development',
                'partner channel', 'reseller', 'commission', 'sales incentive', 'booking',
                'annual recurring revenue', 'arr', 'monthly recurring revenue', 'mrr',
                'average contract value', 'acv', 'total contract value', 'tcv', 'churn',
                'upsell', 'cross-sell', 'account expansion', 'renewal', 'sales playbook',
                'battle card', 'win loss', 'sales enablement', 'sales qualified lead',
                'customer acquisition cost', 'lifetime value', 'net revenue retention', 'nrr',
                'pipeline report', 'sales target', 'close date', 'opportunity stage',
                'go to market', 'bid',
            ],
            'Marketing & Communications': [
                'brand guidelines', 'marketing campaign', 'social media', 'press release',
                'content strategy', 'seo', 'audience targeting', 'advertising', 'brand voice',
                'marketing funnel', 'click-through rate', 'ctr', 'conversion rate', 'cost per click',
                'cpc', 'return on ad spend', 'roas', 'impressions', 'reach', 'engagement rate',
                'email newsletter', 'drip campaign', 'email marketing', 'marketing automation',
                'hubspot', 'marketo', 'google ads', 'pay-per-click', 'ppc', 'display advertising',
                'retargeting', 'landing page', 'lead magnet', 'content calendar', 'whitepaper',
                'public relations', 'media outreach', 'event marketing', 'webinar',
                'brand identity', 'logo usage', 'messaging framework', 'positioning statement',
                'tagline', 'value proposition', 'media kit', 'product launch', 'demand generation',
                'brand awareness', 'thought leadership', 'influencer', 'earned media', 'paid media',
                'content marketing', 'analyst relations', 'conference sponsorship',
            ],
            'Product Development / R&D': [
                'product roadmap', 'sprint', 'backlog', 'user story', 'mvp', 'minimum viable product',
                'prototype', 'feature request', 'a/b test', 'ux research', 'engineering ticket',
                'product requirement', 'product spec', 'functional spec', 'design doc',
                'architecture decision record', 'adr', 'kanban', 'scrum', 'agile', 'epic',
                'story points', 'velocity', 'release planning', 'product vision', 'product strategy',
                'innovation', 'r&d', 'research and development', 'patent pending', 'proof of concept',
                'poc', 'technology evaluation', 'design review', 'code review', 'technical debt',
                'sdk', 'developer documentation', 'integration guide', 'acceptance criteria',
                'definition of done', 'user acceptance testing', 'uat', 'quality assurance',
                'bug report', 'issue tracker', 'jira', 'confluence', 'product analytics',
                'feature flag', 'beta testing', 'design system', 'ux design', 'wireframe',
                'mockup', 'customer feedback', 'nps survey', 'launch plan', 'release notes',
            ],
            'Operations and Internal Documentation': [
                'standard operating procedure', 'sop', 'workflow', 'supply chain', 'logistics',
                'facility', 'meeting minutes', 'operational kpi', 'process improvement',
                'vendor management', 'procurement', 'purchase requisition', 'service level agreement',
                'sla', 'business continuity', 'crisis management', 'risk register', 'risk assessment',
                'project management', 'project plan', 'gantt chart', 'milestone tracking',
                'change management', 'internal memo', 'policy document', 'operational review',
                'capacity planning', 'resource allocation', 'fleet management', 'asset management',
                'maintenance schedule', 'quality control', 'iso certification', 'six sigma',
                'lean process', 'continuous improvement', 'kaizen', 'audit trail', 'internal audit',
                'compliance checklist', 'training material', 'facilities management',
                'travel policy', 'expense policy', 'vendor scorecard', 'contractor management',
                'escalation process', 'change request', 'internal report', 'operational efficiency',
            ],
            'Customer / Client Documentation': [
                'prepared for', 'submitted to', 'engagement summary', 'client onboarding',
                'account summary', 'customer contact', 'client relationship', 'customer success',
                'client status', 'project status report', 'client feedback', 'satisfaction survey',
                'net promoter score', 'customer health score', 'renewal discussion',
                'executive business review', 'qbr', 'client meeting notes', 'account plan',
                'customer journey', 'helpdesk ticket', 'service request', 'client briefing',
                'engagement letter', 'scope confirmation', 'client reference', 'implementation guide',
                'handover document', 'customer story', 'client profile', 'account review',
                'client deliverable', 'weekly update', 'status update',
            ],
        }
        for grp, kws in kw_map.items():
            for kw in kws:
                if kw in cl:
                    domain_scores[grp] += 1

        # Filename boosts
        fn_boosts = {
            'HR': [
                'payroll', 'employee', 'hr_', 'human', 'salary', 'benefits', 'onboard', 'talent',
                'performance', 'hiring', 'recruiting', 'offer_letter', 'termination', 'severance',
                'pip', 'handbook', 'background_check', 'compensation', 'headcount', 'workforce',
            ],
            'Finance and Accounting': [
                'financial', 'budget', 'invoice', 'revenue', 'ledger', 'accounting', 'tax', 'audit',
                'expense', 'payable', 'receivable', 'journal', 'gl_', 'cost', 'profit', 'loss',
                'forecast', 'variance', 'cash', 'treasury', 'fiscal', 'provision', 'write_off',
            ],
            'Legal + Compliance': [
                'contract', 'legal', 'compliance', 'nda', 'agreement', 'policy', 'terms',
                'msa', 'sow', 'license', 'settlement', 'litigation', 'regulatory', 'gdpr',
                'privacy', 'hipaa', 'sox', 'dpa', 'addendum', 'amendment', 'governing',
            ],
            'IT & Systems': [
                'system', 'it_', 'server', 'network', 'infra', 'access_control', 'config',
                'cloud', 'devops', 'api', 'security', 'vpn', 'credential', 'database', 'architecture',
                'firewall', 'dns', 'ssl', 'certificate', 'terraform', 'kubernetes', 'docker',
                'aws', 'azure', 'gcp', 'ssh', 'passcode', 'password', 'access_matrix',
                'building_security', 'cloud_infra', 'technical', 'tech_spec',
            ],
            'Customer / Client Documentation': [
                'client', 'customer', 'account', 'engagement', 'case_study', 'status_report',
                'qbr', 'handover', 'deliverable', 'project_status',
            ],
            'Sales & Business Development': [
                'sales', 'pipeline', 'proposal', 'deal', 'partnership', 'crm', 'opportunity',
                'forecast', 'quota', 'prospect', 'rfp', 'rfq', 'lead', 'business_dev',
            ],
            'Marketing & Communications': [
                'marketing', 'campaign', 'brand', 'comms', 'press_release', 'social_media',
                'advertising', 'content', 'seo', 'email_campaign', 'newsletter', 'media_kit',
            ],
            'Product Development / R&D': [
                'product', 'roadmap', 'r&d', 'research', 'design', 'backlog', 'sprint',
                'prototype', 'mvp', 'feature', 'release', 'ux', 'wireframe', 'spec',
            ],
            'Operations and Internal Documentation': [
                'operation', 'procedure', 'sop', 'internal', 'meeting', 'vendor', 'procurement',
                'workflow', 'process', 'facility', 'sla', 'supply_chain', 'logistics',
                'risk_register', 'continuity', 'change_mgmt',
            ],
        }
        for grp, fns in fn_boosts.items():
            for f in fns:
                if f in fn:
                    domain_scores[grp] += 2  # filename is a strong signal

        sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)
        top_domain, top_score = sorted_domains[0]
        second_domain, second_score = sorted_domains[1] if len(sorted_domains) > 1 else ('', 0)

        return {
            'pii_hits': pii_hits,
            'high_risk_pii': high_risk_pii,
            'contextual_signals': contextual_signals,
            'pii_count': len(pii_hits),
            'high_risk_count': len(high_risk_pii),
            'domain_scores': domain_scores,
            'top_domain': top_domain,
            'top_score': top_score,
            'second_domain': second_domain,
            'second_score': second_score,
            'has_high_pii': len(high_risk_pii) > 0,
        }

    def _post_validate(self, result: dict, pre_analysis: dict) -> dict:
        """Apply rule-based corrections to the LLM output using hard pre-analysis signals."""
        pii = pre_analysis.get('pii_hits', [])
        pii_str = ' '.join(pii).lower()
        top = pre_analysis.get('top_domain', '')
        top_score = pre_analysis.get('top_score', 0)
        cur_group = result.get('functional_group', '')
        scores = pre_analysis.get('domain_scores', {})

        # 1. If high-risk PII found, always force High sensitivity
        if pre_analysis.get('has_high_pii'):
            result['sensitivity_level'] = 'High'
            cur_risk = float(result.get('risk_score', 5))
            result['risk_score'] = max(cur_risk, 7.5)

        # 2. If model missed PII types that we definitively found, add them
        existing_pii = [p.split(':')[0].strip().lower() for p in result.get('pii_detected', [])]
        for hit in pii:
            hit_type = hit.split(':')[0].split('(')[0].strip()
            if not any(hit_type.lower() in ep for ep in existing_pii):
                result.setdefault('pii_detected', []).append(hit_type)

        # 3. If domain score strongly favors a group the model missed, override
        # Only override when the score gap is decisive (4+) AND model picked a weak match
        if top_score >= 4 and cur_group != top:
            weak_groups = {'Customer / Client Documentation', 'Outliers / Others',
                           'Operations and Internal Documentation'}
            if cur_group in weak_groups and top not in weak_groups:
                result['functional_group'] = top
                result.setdefault('reasoning', '')
                result['reasoning'] = (f"[Post-validator overrode '{cur_group}' → '{top}' "
                    f"based on keyword score {top_score} vs runner-up {pre_analysis.get('second_score',0)}] "
                    + result['reasoning'])

        # 4. Bump risk_score only when genuine high-risk PII is present
        # (email addresses, phone numbers, dollar amounts alone do NOT bump risk)
        n_high_risk = len(pre_analysis.get('high_risk_pii', []))
        if n_high_risk >= 3:
            result['risk_score'] = max(float(result.get('risk_score', 5)), 8.0)
        elif n_high_risk >= 2:
            result['risk_score'] = max(float(result.get('risk_score', 5)), 6.5)
        elif n_high_risk == 1:
            result['risk_score'] = max(float(result.get('risk_score', 5)), 5.5)

        return result

    # Control characters / injection patterns to strip from user-supplied strings
    _CTRL_STRIP = re.compile(r'[\r\n\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
    # Prompt-injection phrases sometimes embedded in filenames or document text
    _INJECT_STRIP = re.compile(
        r'(ignore (all |previous |prior |above )?(instructions?|prompts?|rules?)|'
        r'system prompt|you are now|forget (everything|all)|do not classify|'
        r'override (instructions?|classification))',
        re.IGNORECASE
    )

    def _build_prompt(self, content: str, file_name: str, file_size: int = None,
                      pre_analysis: dict = None) -> str:
        """Build Gemini prompt for classification with enhanced sensitivity analysis and PII detection."""
        sensitivity_str = ', '.join(self.SENSITIVITY_LEVELS)
        pre_analysis = pre_analysis or {}

        # --- Sanitize user-supplied inputs before embedding in prompt ---
        # Strip control characters and newlines from filename (prevents log/prompt injection)
        file_name = self._CTRL_STRIP.sub('', str(file_name))[:255]
        # Remove obvious prompt-injection phrases from filename
        file_name = self._INJECT_STRIP.sub('[removed]', file_name)
        # Strip null bytes from content; hard cap already applied below
        content = self._CTRL_STRIP.sub(' ', str(content))

        # Smart chunking: take first 10 000 + last 2 000 chars for large docs
        max_content = 12000
        content_truncated = False
        if len(content) > max_content:
            first_part = content[:10000]
            last_part  = content[-2000:]
            content = first_part + '\n\n[... middle section omitted for length ...]\n\n' + last_part
            content_truncated = True

        # Build pre-analysis cheat-sheet block
        high_risk_pii = pre_analysis.get('high_risk_pii', [])
        contextual_signals = pre_analysis.get('contextual_signals', [])
        pii_hits = pre_analysis.get('pii_hits', [])
        top_domain  = pre_analysis.get('top_domain', 'Unknown')
        top_score   = pre_analysis.get('top_score', 0)
        second_domain = pre_analysis.get('second_domain', '')
        second_score  = pre_analysis.get('second_score', 0)
        domain_scores_sorted = sorted(
            (pre_analysis.get('domain_scores') or {}).items(),
            key=lambda x: x[1], reverse=True
        )[:5]
        ds_lines = '  ' + '\n  '.join(f"{g}: {s}" for g, s in domain_scores_sorted) if domain_scores_sorted else '  (none)'

        pre_block = f"""--- PRE-ANALYSIS SIGNALS (extracted by deterministic regex scan — treat as ground truth) ---
HIGH-RISK PII detected (SSN, credentials, account numbers, salary, medical — REQUIRE High sensitivity if present):
{chr(10).join('  - ' + h for h in high_risk_pii) if high_risk_pii else '  None detected'}

Contextual signals (email addresses, phone numbers, regulatory mentions, dollar amounts — informational only, do NOT automatically force High sensitivity):
{chr(10).join('  - ' + h for h in contextual_signals) if contextual_signals else '  None detected'}

Keyword domain scores (higher = stronger evidence):
{ds_lines}
  Top domain: {top_domain} (score {top_score})  Runner-up: {second_domain} (score {second_score})
--- END PRE-ANALYSIS ---
"""

        prompt = f"""You are a document classification expert with deep knowledge of business records and data governance. Analyze the following document and classify it into ONE of the 10 functional groups below.

{pre_block}
IMPORTANT: The PRE-ANALYSIS SIGNALS above were extracted by deterministic regex patterns and are highly reliable. Use them to:
- Confirm or upgrade sensitivity level ONLY when HIGH-RISK PII was found (SSN, account numbers, passwords, API keys, salary data, medical data). Contextual signals like email addresses, phone numbers, or regulatory framework mentions alone do NOT force High sensitivity.
- Validate or adjust your functional group choice (high keyword score for a domain is strong evidence)
- Populate pii_detected with the specific types listed (add exact examples from the document)

ENHANCED SENSITIVITY CLASSIFICATION LOGIC:

HIGH SENSITIVITY - Document must contain AT LEAST ONE of these specific items:
- Personal identifiers: Actual SSNs (###-##-#### pattern), passport numbers, driver's license numbers with personal details
- Financial account data: Actual bank account numbers, credit card numbers, routing numbers, IBAN/SWIFT codes, wire transfer instructions with account details
- Payroll/salary records: Specific named individual salary figures, payroll run data, compensation files
- Security credentials: Actual working API keys, passwords, encryption keys, database connection strings, access tokens (NOT placeholder examples)
- Protected health information: Actual medical records, patient IDs, health insurance claim files
- Active legal matters: Litigation case files with financial exposure, signed settlement agreements with dollar amounts, active regulatory violation notices
- Executive/board confidential: C-level individual compensation, M&A target documents, board meeting minutes with strategic decisions

MODERATE SENSITIVITY - Document contains sensitive business information but NO high-risk PII above:
- Financial reports and forecasts with dollar figures (budgets, P&L, revenue forecasts) — NOT account numbers
- Internal business strategy, competitive analysis, or confidential planning documents
- Client contact information (names, emails, phone numbers) or client-specific pricing
- Performance reviews, employee evaluations (without SSNs or payroll data)
- Internal security procedures and policies (without actual credentials)
- Standard vendor/service contracts, NDAs, procurement agreements
- Employee organizational information (org charts, headcount reports)
- Internal meeting notes with business-sensitive discussions
- Any document containing email addresses or phone numbers as its most sensitive element

LOW SENSITIVITY - Document contains:
- Public-facing marketing content, press releases, brand guidelines
- Generic standard operating procedures (SOPs) without sensitive data examples
- Published materials or external communications
- General training documentation without sensitive examples
- General process documentation, workflow descriptions
- Employee handbooks, company policies with no personal employee data
- Informational documents that only mention regulatory frameworks (e.g. a document explaining what GDPR is, or a compliance checklist)

PII DETECTION PATTERNS TO IDENTIFY:
- Social Security Numbers: XXX-XX-XXXX, XXXXXXXXX (9 digits)
- Credit Card Numbers: 16-digit sequences, often grouped in 4s
- Bank Account Numbers: 8-17 digit sequences after "Account:" or "Acct:"
- Routing Numbers: 9-digit ABA/RTN numbers after "Routing:", "ABA:", "RTN:"
- Wire Transfer Details: SWIFT/BIC codes, IBAN numbers, wire transfer instructions
- Employee IDs: Alphanumeric codes like EMP12345, 12345, E-12345
- Phone Numbers: (XXX) XXX-XXXX, XXX-XXX-XXXX, international formats
- Email Addresses: username@domain patterns
- Addresses: Street number + street name + city/state/zip patterns
- Passport Numbers: Country-specific alphanumeric patterns
- Driver's License: State-specific alphanumeric patterns

FUNCTIONAL GROUP DEFINITIONS:

1. HR (Human Resources)
   Scope: Employee lifecycle and workforce management documentation
   Includes: Payroll records, performance evaluations, benefits enrollment, recruiting materials, disciplinary actions, compensation planning, employee IDs, background checks, HR investigations
   Strong indicators: SSNs, employee numbers, salary figures, review language, benefits elections
   EXCLUDE: If document primarily concerns legal contract negotiation or regulatory compliance → use Legal + Compliance instead

2. Finance and Accounting
   Scope: Financial reporting, accounting records, tax, and monetary transactions
   Includes: General ledger extracts, revenue recognition analysis, tax filings, budget forecasts, expense reporting, accounts payable/receivable, bank statements, financial audit schedules
   Strong indicators: GL codes, balance sheets, EBITDA, account numbers, invoices, journal entries
   EXCLUDE: If contract language dominates → classify as Legal instead

3. Legal + Compliance
   Scope: Contracts, regulatory filings, litigation, and compliance documentation
   Includes: NDAs, Master Service Agreements, Data Processing Agreements, litigation memos, regulatory submissions, internal policy documents, compliance certifications
   Strong indicators: "Whereas," indemnification clauses, jurisdiction references, regulatory citations
   EXCLUDE: If document is internal operational guidance → use Operations instead

4. Customer / Client Documentation
   Scope: Generic client engagement deliverables where no dominant functional topic exists
   Includes: Client status reports, onboarding packs, account summaries, engagement letters, project milestone summaries, customer contact records, case files with no strong technical/HR/finance topic
   Strong indicators: Client names, account IDs, "Prepared for [Client]", "Submitted to [Client]", engagement references — BUT ONLY when the document has no dominant IT / HR / Finance / Legal subject
   CRITICAL RULE: If a consulting report, advisory deliverable, or client presentation has a DOMINANT subject-matter topic (IT architecture, workforce planning, financial analysis, legal review, etc.) → classify by that topic (IT & Systems, HR, Finance, etc.) NOT here. Customer/Client Documentation is the bucket for deliverables that are purely about client management, relationship, or generic progress with no clear functional discipline.
   EXCLUDE: Consulting reports with clear technical / IT content → IT & Systems
   EXCLUDE: Consulting reports with clear HR / workforce content → HR
   EXCLUDE: Consulting reports with clear financial modeling content → Finance
   EXCLUDE: If document is about marketing outreach to prospects → Sales or Marketing

5. Sales & Business Development
   Scope: Revenue generation activities and deal tracking
   Includes: Pipeline reports, pricing proposals, sales forecasts, CRM exports, opportunity tracking
   Strong indicators: Deal stage, win probability, prospect list, pricing model drafts

6. Marketing & Communications
   Scope: External messaging and brand communication
   Includes: Press releases, campaign strategies, social media plans, brand guidelines, website content drafts
   Strong indicators: Campaign messaging, brand voice, marketing KPIs

7. IT & Systems
   Scope: Technology infrastructure, system operations, and cloud computing
   Includes: Architecture diagrams, API documentation, access logs, incident reports, system configuration files,
             cloud infrastructure documents (AWS, Azure, GCP), VPN configuration and credentials, network topology,
             load balancer setup, Kubernetes/Docker/Terraform configs, CI/CD pipelines, SSL certificates,
             database server credentials, server inventory, firewall rules, DNS records, monitoring/alerting setup,
             remote access credentials, security key management, cloud migration plans, infrastructure-as-code
   Strong indicators: IP addresses, server names, encryption keys, technical code snippets, cloud provider names
                      (AWS, Azure, GCP, Cloudflare), routing/CIDR notation, port numbers, API keys, SSH keys,
                      Kubernetes, Terraform, Docker, VPN, SWIFT codes for IT systems, IAM policies, VPC configs,
                      hostnames, AMI IDs, container registry, access key IDs, secret access keys

8. Product Development / R&D
   Scope: Research, design, innovation, product strategy
   Includes: Roadmaps, prototype specifications, engineering documentation, product feature requirements
   Strong indicators: Version numbers, feature backlog, design iterations

9. Operations and Internal Documentation
   Scope: Internal process documentation not specific to HR, Finance, or Legal
   Includes: SOPs, internal policy manuals, training documentation, workflow descriptions, meeting minutes

10. Outliers / Others
    Use ONLY if document does not clearly fit any of the above or contains generic administrative content

DISAMBIGUATION RULES - Use these to resolve ambiguous documents:

CONSULTING / ADVISORY DOCUMENTS — classify by PRIMARY SUBJECT MATTER, not delivery format:
- Consulting report with IT architecture, digital maturity, cloud, systems, infrastructure content → IT & Systems
- Consulting report with workforce planning, HR strategy, talent management content → HR
- Consulting report with financial models, budgeting, accounting analysis content → Finance and Accounting
- Consulting report with regulatory, legal, compliance review content → Legal + Compliance
- Consulting report with product strategy, roadmap, R&D content → Product Development / R&D
- Consulting report with sales pipeline, go-to-market strategy content → Sales & Business Development
- Consulting report with marketing campaigns, brand strategy content → Marketing & Communications
- Consulting report with MIXED topics or no dominant functional topic → Customer / Client Documentation
- Generic client status report, onboarding summary, account management record → Customer / Client Documentation

If document contains BOTH features from multiple categories:
- IT architecture + digital transformation + maturity model→ IT & Systems (not Customer)
- Client name + technical architecture diagrams + system recommendations → IT & Systems (not Customer)
- Engagement letter / scope of work + pricing for a client → Sales & Business Development
- Salary data + employee ID → HR (not Finance)
- Revenue schedule + journal entries + GL codes → Finance (not HR or Sales)
- Indemnification clause + governing law + legal liability → Legal (not Finance or Customer)
- Client deliverable with NO dominant functional topic + engagement reference → Customer Documentation
- Opportunity stage + pipeline metrics + win probability → Sales (not Marketing)
- Campaign launch metrics + audience targets + messaging → Marketing (not Sales)
- Server logs + IP addresses + technical configs → IT & Systems
- Cloud infrastructure (AWS/Azure/GCP) + server configs + credentials → IT & Systems
- VPN credentials + remote access + network configs → IT & Systems
- Cloud migration + load balancer + Kubernetes/Terraform → IT & Systems
- Feature backlog + sprint notes + engineering tickets → Product Development (not Operations)
- Internal SOP without regulated data → Operations (not Legal or IT)
- Performance metrics + operational procedures → Operations (not Finance)

PRIORITY ORDER for ambiguous documents:
1. If contains regulated data or legal language → Legal + Compliance
2. If contains employee/payroll data → HR
3. If contains financial accounts/GL codes → Finance
4. If contains technical infrastructure/servers/APIs/cloud configs/VPN/credentials → IT & Systems
5. If contains product features/engineering → Product Development / R&D
6. If contains sales pipeline/opportunity data → Sales & Business Development
7. If contains marketing campaign/messaging → Marketing & Communications
8. If contains internal processes/procedures with no external client → Operations
9. If is a consulting/advisory document or client deliverable with NO dominant topic from groups 1-8 → Customer / Client Documentation
10. If truly unclassifiable with no business context → Outliers / Others
NOTE: A consulting or advisory document is NOT automatically Customer/Client. Always look at WHAT it is about first. A consulting report about IT should be IT & Systems. A consulting report about HR policies should be HR. Only pure relationship/engagement management documents with no functional discipline belong in Customer/Client.
NOTE: "Outliers / Others" should ONLY be used for truly unclassifiable documents (e.g., blank files, corrupted text, completely generic templates with zero business context). If you can determine ANY purpose, use one of the first 9 groups.

SENSITIVITY LEVELS: {sensitivity_str}
- Low: General information, public-facing content, non-sensitive business documentation
- Moderate: Contains some business-sensitive information but not critical employee/financial/legal data
- High: Contains PII (SSNs, employee IDs), financial account data, confidential contracts, proprietary information, regulated data

DOCUMENT METADATA:
- Filename: {file_name}
{"- File size: " + str(file_size) + " bytes" if file_size else ""}
{"- Content note: Large document — showing first 10,000 + last 2,000 characters" if content_truncated else ""}

DOCUMENT CONTENT:{" (truncated — first 10k + last 2k chars)" if content_truncated else ""}
{content}

ENHANCED CLASSIFICATION INSTRUCTIONS:
1. FIRST review the PRE-ANALYSIS SIGNALS at the top — they are deterministic regex results, not guesses.
2. If the pre-analysis found HIGH-RISK PII (SSN, credit card, bank account, routing number, password, API key, salary/payroll data, medical data, wire transfer details) → sensitivity MUST be High.
3. Contextual signals (email address, phone number, regulatory framework mention, general dollar amounts in reports) are informational — they should influence your judgment but do NOT automatically force High. A budget report with dollar figures is Moderate. A marketing doc with an email address is Low or Moderate.
3. If the pre-analysis keyword domain scores show a clear winner (score ≥ 4), weight that heavily when choosing the functional group.
4. Then read the full document content, scanning for additional context and specific PII examples to cite.
5. Identify the PRIMARY SUBJECT MATTER of the document — what field or discipline is this fundamentally about?
6. Apply PRIORITY ORDER: classify by primary subject matter (IT, HR, Finance, Legal, Product, Sales, Marketing, Operations) before considering delivery format.
7. Only use "Customer / Client Documentation" for documents whose primary subject is client relationship management or mixed-topic deliverables with no dominant functional discipline.
8. Apply DISAMBIGUATION RULES — consulting/advisory documents are classified by WHAT subject they cover, not WHO they were written for.
9. MUST classify to ONE of the first 9 groups — avoid "Outliers / Others" unless absolutely impossible.
10. Provide TWO confidence scores: functional_group_confidence (0.0-1.0) and sensitivity_confidence (0.0-1.0).
11. Calculate risk_score (0-10): High sensitivity WITH 2+ high-risk PII types = 8-10; High WITH 1 high-risk PII type = 6-8; Moderate = 3-6; Low = 0-3. A document with only email addresses or phone numbers should score 2-4 maximum.
12. In pii_detected, include SPECIFIC EXAMPLES lifted from the document (e.g., "SSN: 123-45-6789", "Email: john@example.com").
13. In reasoning, QUOTE specific text from the document to justify every classification decision.

RESPOND IN JSON FORMAT ONLY — no markdown, no code fences:
{{
  "functional_group": "<one of the first 9 groups — avoid Outliers unless impossible>",
  "functional_group_confidence": <0.0-1.0>,
  "sensitivity_level": "<Low|Moderate|High>",
  "sensitivity_confidence": <0.0-1.0>,
  "risk_score": <0-10 numeric>,
  "document_summary": "<2-3 sentence plain-English overview: what this document is, what data it contains, and its purpose>",
  "confidential_findings": ["<specific finding with exact value, e.g. 'SSN 123-45-6789 found in employee record section'>"],
  "pii_detected": ["<PII type with example value, e.g. 'SSN: 123-45-6789', 'Email: j.smith@company.com'>"],
  "reasoning": "<Detailed explanation quoting specific document text. State: 1) what PII was found and where, 2) why this functional group was chosen over alternatives, 3) what drove the sensitivity level.>"
}}
"""
        return prompt

    def _parse_response(self, response_text: str) -> Dict:
        """
        Parse Gemini API response JSON.

        Args:
            response_text: Raw response from API

        Returns:
            Parsed classification result dict
        """
        try:
            import re as _re
            # Strip markdown code fences (```json ... ``` or ``` ... ```)
            text = response_text.strip()
            fence = _re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
            if fence:
                json_str = fence.group(1).strip()
            else:
                # Extract first {...} block
                brace = _re.search(r'\{[\s\S]*\}', text)
                json_str = brace.group(0).strip() if brace else text

            result = json.loads(json_str)

            # Validate result
            if 'functional_group' not in result:
                raise ValueError("Missing functional_group in response")
            if 'sensitivity_level' not in result:
                raise ValueError("Missing sensitivity_level in response")

            # Normalize values
            result['functional_group'] = str(result['functional_group']).strip()
            result['sensitivity_level'] = str(result['sensitivity_level']).strip()

            # ── Fuzzy-match functional_group so minor Gemini phrasing variations
            #    don't trigger the fallback path (e.g. "IT and Systems" → "IT & Systems")
            GROUP_ALIASES = {
                'it & systems': 'IT & Systems',
                'it and systems': 'IT & Systems',
                'it systems': 'IT & Systems',
                'information technology': 'IT & Systems',
                'it & systems management': 'IT & Systems',
                'hr': 'HR',
                'human resources': 'HR',
                'human resources (hr)': 'HR',
                'finance': 'Finance and Accounting',
                'finance & accounting': 'Finance and Accounting',
                'finance and accounting': 'Finance and Accounting',
                'financial': 'Finance and Accounting',
                'legal': 'Legal + Compliance',
                'legal and compliance': 'Legal + Compliance',
                'legal & compliance': 'Legal + Compliance',
                'legal + compliance': 'Legal + Compliance',
                'legal/compliance': 'Legal + Compliance',
                'customer': 'Customer / Client Documentation',
                'client': 'Customer / Client Documentation',
                'customer/client documentation': 'Customer / Client Documentation',
                'customer / client': 'Customer / Client Documentation',
                'sales': 'Sales & Business Development',
                'sales & business development': 'Sales & Business Development',
                'sales and business development': 'Sales & Business Development',
                'marketing': 'Marketing & Communications',
                'marketing & communications': 'Marketing & Communications',
                'marketing and communications': 'Marketing & Communications',
                'product development': 'Product Development / R&D',
                'product development / r&d': 'Product Development / R&D',
                'product development/r&d': 'Product Development / R&D',
                'r&d': 'Product Development / R&D',
                'research and development': 'Product Development / R&D',
                'operations': 'Operations and Internal Documentation',
                'operations and internal documentation': 'Operations and Internal Documentation',
                'internal operations': 'Operations and Internal Documentation',
                'outliers': 'Outliers / Others',
                'others': 'Outliers / Others',
                'outliers / others': 'Outliers / Others',
                'other': 'Outliers / Others',
                'uncategorized': 'Outliers / Others',
            }
            normalized_key = result['functional_group'].lower().strip()
            if result['functional_group'] not in self.FUNCTIONAL_GROUPS:
                if normalized_key in GROUP_ALIASES:
                    result['functional_group'] = GROUP_ALIASES[normalized_key]
                else:
                    # Try partial match — pick the canonical group whose lowercase
                    # name is contained in or contains the returned value
                    for canonical in self.FUNCTIONAL_GROUPS:
                        if canonical.lower() in normalized_key or normalized_key in canonical.lower():
                            result['functional_group'] = canonical
                            break
            result['functional_group_confidence'] = float(result.get('functional_group_confidence', 0.5))
            result['sensitivity_confidence'] = float(result.get('sensitivity_confidence', 0.5)) 
            result['confidence'] = float(result.get('functional_group_confidence', 0.5))  # Legacy compatibility
            result['risk_score'] = float(result.get('risk_score', 5.0))
            result['document_summary'] = str(result.get('document_summary', ''))
            result['confidential_findings'] = result.get('confidential_findings', [])
            result['pii_detected'] = result.get('pii_detected', [])
            result['reasoning'] = str(result.get('reasoning', 'No explanation provided'))

            # Validate against allowed values
            if result['functional_group'] not in self.FUNCTIONAL_GROUPS:
                logger.warning(
                    f"Invalid group '{result['functional_group']}' - using fallback"
                )
                raise ValueError(f"Invalid functional_group: {result['functional_group']}")

            if result['sensitivity_level'] not in self.SENSITIVITY_LEVELS:
                logger.warning(
                    f"Invalid sensitivity '{result['sensitivity_level']}' - using fallback"
                )
                raise ValueError(f"Invalid sensitivity_level: {result['sensitivity_level']}")

            result['classification_status'] = 'success'
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Response text: {response_text[:200]}")
            raise ValueError("Invalid JSON in API response")

    # ──────────────────────────────────────────────────────────────────────────
    # Ollama local-LLM fallback
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        """Return True when the exception looks like a Gemini quota / rate-limit error."""
        msg = str(exc).lower()
        quota_signals = [
            'resource_exhausted', 'resourceexhausted',
            'quota exceeded', 'quota_exceeded',
            'rate limit', 'rate_limit',
            '429',
            'too many requests',
        ]
        return any(s in msg for s in quota_signals)

    def _classify_with_groq(
        self,
        prompt: str,
        pre_analysis: dict,
        file_name: str,
        content: str = None,
    ) -> Dict:
        """Try to classify using the Groq API (fast LLM inference).
        Falls back to Ollama if Groq key is missing or the call fails.

        Requires:  pip install groq
        Set GROQ_API_KEY and optionally GROQ_MODEL (default llama-3.3-70b-versatile).
        """
        if not self.groq_api_key:
            logger.info("GROQ_API_KEY not set — skipping Groq, trying Ollama")
            return self._classify_with_ollama(prompt, pre_analysis, file_name, content)

        try:
            from groq import Groq
            client = Groq(api_key=self.groq_api_key)
            logger.info(f"Calling Groq ({self.groq_model}) for {file_name}")
            completion = client.chat.completions.create(
                model=self.groq_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=800,
            )
            text = completion.choices[0].message.content if completion.choices else ''
            if not text:
                raise ValueError('Empty response from Groq')

            result = self._parse_response(text)
            result = self._post_validate(result, pre_analysis)
            result['classification_status'] = 'success'
            result['model_used'] = f'groq/{self.groq_model}'
            logger.info(f"Groq classification succeeded for {file_name}")
            return result

        except ImportError:
            logger.warning("groq package not installed — falling back to Ollama")
        except Exception as e:
            logger.warning(f"Groq classification failed ({e}) — falling back to Ollama")

        return self._classify_with_ollama(prompt, pre_analysis, file_name, content)

    def _classify_with_ollama(
        self,
        prompt: str,
        pre_analysis: dict,
        file_name: str,
        content: str = None,
    ) -> Dict:
        """Try to classify using a local Ollama server.  Falls back to keyword
        classifier if Ollama is not running or returns an unparseable response.

        Ollama must be installed and running:  https://ollama.com/download
        Pull a model first:  ollama pull llama3.2
        The server is expected at OLLAMA_URL (default http://localhost:11434).
        """
        import urllib.request
        import urllib.error

        try:
            url = f"{self.ollama_url.rstrip('/')}/api/generate"
            payload = json.dumps({
                'model': self.ollama_model,
                'prompt': prompt,
                'stream': False,
                'options': {
                    'temperature': 0.1,   # low temp = deterministic classification
                    'num_predict': 800,
                },
            }).encode('utf-8')

            req = urllib.request.Request(
                url,
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )

            logger.info(f"Calling Ollama ({self.ollama_model}) at {url}")
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode('utf-8'))

            text = body.get('response', '')
            if not text:
                raise ValueError('Empty response from Ollama')

            result = self._parse_response(text)
            result = self._post_validate(result, pre_analysis)
            result['classification_status'] = 'success'
            result['model_used'] = f'ollama/{self.ollama_model}'
            logger.info(f"Ollama classification succeeded for {file_name}")
            return result

        except urllib.error.URLError as e:
            logger.warning(f"Ollama not reachable ({e}) — using keyword fallback")
        except Exception as e:
            logger.warning(f"Ollama classification failed ({e}) — using keyword fallback")

        # Last resort: pure keyword-based classification
        result = self._fallback_classification(file_name, content)
        result['model_used'] = 'keyword_fallback'
        return result

    def _fallback_classification(self, file_name: str, content: str = None) -> Dict:
        """
        Enhanced fallback classification based on filename and content analysis.
        Used when API is unavailable or fails.

        Args:
            file_name: Document filename
            content: Optional document content for enhanced analysis

        Returns:
            Enhanced fallback classification result
        """
        file_lower = file_name.lower()
        content_lower = (content or '').lower()
        
        # Initialize classification variables
        group = 'Outliers / Others'
        sensitivity = 'Low'
        confidence = 0.3
        pii_detected = []
        risk_score = 2
        reasoning_factors = []
        
        # Enhanced PII detection patterns for fallback
        if content:
            # SSN patterns
            import re
            ssn_pattern = r'\b\d{3}-\d{2}-\d{4}\b|\b\d{9}\b'
            if re.search(ssn_pattern, content):
                pii_detected.append('SSN')
                sensitivity = 'High'
                risk_score = max(risk_score, 9)
                reasoning_factors.append('Contains Social Security Numbers')
            
            # Credit card patterns (basic)
            cc_pattern = r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'
            if re.search(cc_pattern, content):
                pii_detected.append('Credit Card')
                sensitivity = 'High' 
                risk_score = max(risk_score, 9)
                reasoning_factors.append('Contains credit card numbers')
            
            # Bank account patterns
            bank_pattern = r'\b(?:account|acct)(?:#|:|\s+)?\s*\d{8,17}\b'
            if re.search(bank_pattern, content_lower):
                pii_detected.append('Bank Account')
                sensitivity = 'High'
                risk_score = max(risk_score, 8)
                reasoning_factors.append('Contains bank account information')

            # Routing number patterns (ABA: exactly 9 digits, often preceded by 'routing')
            routing_pattern = r'\b(?:routing(?:\s+number)?|aba(?:\s+number)?|rtn)(?:\s*[:#=]?\s*)\d{9}\b|\b0[0-2]\d{7}\b'
            if re.search(routing_pattern, content_lower):
                pii_detected.append('Routing Number')
                sensitivity = 'High'
                risk_score = max(risk_score, 8)
                reasoning_factors.append('Contains bank routing number')

            # Wire transfer / SWIFT / IBAN
            wire_pattern = r'\b(?:wire\s+transfer|swift\s*(?:code|bic)?|iban)(?:\s*[:#=]?\s*)[A-Z0-9]{8,34}\b'
            if re.search(wire_pattern, content_lower, re.IGNORECASE):
                pii_detected.append('Wire Transfer Details')
                sensitivity = 'High'
                risk_score = max(risk_score, 9)
                reasoning_factors.append('Contains wire transfer / SWIFT / IBAN details')
            
            # Password patterns
            password_pattern = r'\b(?:password|pwd|pass)(?:\s*[:=]\s*|\s+)[\w!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]{6,}'
            if re.search(password_pattern, content_lower):
                pii_detected.append('Passwords/Credentials')
                sensitivity = 'High'
                risk_score = max(risk_score, 9)
                reasoning_factors.append('Contains passwords or credentials')
            
            # Employee ID patterns
            emp_id_pattern = r'\b(?:employee\s+id|emp[-_]?\d+|e[-_]?\d{5,})\b'
            if re.search(emp_id_pattern, content_lower):
                pii_detected.append('Employee ID')
                sensitivity = 'High' if any(other in pii_detected for other in ['SSN', 'Bank Account']) else 'Moderate'
                risk_score = max(risk_score, 7)
                reasoning_factors.append('Contains employee identification')
            
            # Salary/compensation patterns 
            salary_pattern = r'\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*(?:annually|yearly|per\s+year|salary|compensation)'
            if re.search(salary_pattern, content_lower):
                pii_detected.append('Salary Information')
                sensitivity = 'High' if 'HR' in group or any(word in content_lower for word in ['payroll', 'compensation', 'benefits']) else 'Moderate'
                risk_score = max(risk_score, 7)
                reasoning_factors.append('Contains salary/compensation data')
            
            # API keys and tokens
            api_pattern = r'\b(?:api[_\s]*key|access[_\s]*token|secret[_\s]*key)[:=\s]+[a-zA-Z0-9_\-]{20,}\b'
            if re.search(api_pattern, content_lower):
                pii_detected.append('API Keys/Tokens')
                sensitivity = 'High'
                risk_score = max(risk_score, 9)
                reasoning_factors.append('Contains API keys or access tokens')

        # Enhanced filename-based classification with content validation
        if any(x in file_lower for x in ['payroll', 'employee', 'benefit', 'hr_', 'human', 'salary', 'compensation']):
            group = 'HR'
            confidence = 0.8 if any(x in content_lower for x in ['ssn', 'social security', 'salary', 'payroll', 'employee id']) else 0.6
            sensitivity = 'High' if pii_detected or any(x in content_lower for x in ['ssn', 'social security', 'bank account']) else 'Moderate'
            reasoning_factors.append('HR-related filename and content indicators')
            
        elif any(x in file_lower for x in ['financial', 'budget', 'invoice', 'revenue', 'expense', 'accounting', 'ledger']):
            group = 'Finance and Accounting'
            confidence = 0.8 if any(x in content_lower for x in ['account number', 'bank', 'financial', 'revenue', 'expense']) else 0.6
            sensitivity = 'High' if pii_detected else 'Moderate'
            reasoning_factors.append('Finance-related filename and content indicators')
            
        elif any(x in file_lower for x in ['contract', 'legal', 'compliance', 'policy', 'terms', 'agreement']):
            group = 'Legal + Compliance'
            confidence = 0.7 if any(x in content_lower for x in ['contract', 'agreement', 'legal', 'compliance', 'whereas']) else 0.5
            sensitivity = 'High' if pii_detected else 'Moderate'
            reasoning_factors.append('Legal/compliance-related filename')
            
        elif any(x in file_lower for x in ['customer', 'client', 'account']):
            group = 'Customer / Client Documentation'
            confidence = 0.7 if any(x in content_lower for x in ['client', 'customer', 'account', 'deliverable']) else 0.5
            sensitivity = 'High' if pii_detected else 'Moderate'
            reasoning_factors.append('Customer/client-related filename')
            
        elif any(x in file_lower for x in ['sales', 'proposal', 'lead', 'deal', 'partnership', 'crm']):
            group = 'Sales & Business Development'
            confidence = 0.7 if any(x in content_lower for x in ['sales', 'proposal', 'deal', 'pipeline', 'opportunity']) else 0.5
            sensitivity = 'High' if pii_detected else 'Moderate'
            reasoning_factors.append('Sales/business development filename')
            
        elif any(x in file_lower for x in ['marketing', 'campaign', 'brand', 'communication', 'social']):
            group = 'Marketing & Communications'
            # Check for social media credentials which should be high sensitivity
            if any(x in file_lower for x in ['credential', 'password', 'access', 'social_media', 'login']):
                sensitivity = 'High'
                confidence = 0.9
                risk_score = max(risk_score, 8)
                reasoning_factors.append('Marketing credentials detected - high security risk')
            elif pii_detected:
                sensitivity = 'High'
                confidence = 0.7
            else:
                sensitivity = 'Low'
                confidence = 0.6
            reasoning_factors.append('Marketing-related filename')
            
        elif any(x in file_lower for x in ['system', 'it_', 'server', 'network', 'infrastructure', 'access_control', 'admin',
                                              'vpn', 'credential', 'api_key', 'api-key', 'token', 'auth', 'config',
                                              'certificate', 'cert', 'ssh', 'firewall', 'cloud', 'devops', 'database']):
            group = 'IT & Systems'
            # IT documents with access info are extremely high risk
            if any(x in file_lower for x in ['access', 'credential', 'password', 'admin', 'control']) or any(x in content_lower for x in ['password', 'admin', 'root', 'domain admin']):
                sensitivity = 'High'
                confidence = 0.9
                risk_score = max(risk_score, 10)  # Maximum risk for IT credentials
                reasoning_factors.append('IT access control document - maximum security risk')
            elif pii_detected:
                sensitivity = 'High'
                confidence = 0.8
            else:
                sensitivity = 'Moderate'
                confidence = 0.6
            reasoning_factors.append('IT/systems-related filename')
            
        elif any(x in file_lower for x in ['product', 'r&d', 'research', 'design', 'development']):
            group = 'Product Development / R&D'
            confidence = 0.6 if any(x in content_lower for x in ['product', 'research', 'development', 'design']) else 0.4
            sensitivity = 'High' if pii_detected else 'Moderate'
            reasoning_factors.append('Product/R&D-related filename')
            
        elif any(x in file_lower for x in ['operation', 'procedure', 'meeting', 'internal', 'sop']):
            group = 'Operations and Internal Documentation'
            confidence = 0.6 if any(x in content_lower for x in ['procedure', 'operation', 'process', 'sop']) else 0.4
            sensitivity = 'High' if pii_detected else 'Low'
            reasoning_factors.append('Operations/internal document')

        # ── CONTENT-BASED FALLBACK ──────────────────────────────────────
        # Filename gave no match → score each group by keyword hits in content.
        # This handles consulting reports, generic filenames, etc.
        if group == 'Outliers / Others' and content:
            import re as _re2
            scores = {g: 0 for g in self.FUNCTIONAL_GROUPS if g != 'Outliers / Others'}

            kw_map = {
                'IT & Systems': [
                    'cloud', 'aws', 'amazon web services', 'azure', 'microsoft azure', 'gcp', 'google cloud',
                    'kubernetes', 'k8s', 'docker', 'terraform', 'infrastructure', 'api gateway', 'devops',
                    'ci/cd', 'cicd', 'deployment', 'container', 'serverless', 'microservice', 'microservices',
                    'postgresql', 'mongodb', 'redis', 'dynamodb', 'elasticsearch', 'hashicorp', 'vault',
                    'waf', 'edr', 'firewall', 'vpn', 'technology stack', 'tech stack', 'digital transformation',
                    'digital maturity', 'cloud-native', 'cloud native', 'cloud migration', 'legacy system',
                    'blue-green', 'strangler pattern', 'frontend', 'backend', 'database server', 'load balancer',
                    'api key', 'api keys', 'access token', 'bearer token', 'refresh token', 'oauth', 'saml',
                    'authentication', 'authorization', 'credential', 'credentials', 'password', 'passphrase',
                    'network administration', 'remote access', 'remote desktop', 'rdp', 'ssh', 'ssl', 'tls',
                    'certificate', 'ldap', 'active directory', 'iam', 'service account',
                    'access control', 'network topology', 'subnet', 'ip address', 'ip addresses', 'cidr', 'dns',
                    'patch management', 'vulnerability', 'penetration test', 'security audit',
                    'incident response', 'siem', 'intrusion detection', 'endpoint security',
                    'passcode', 'building security', 'access badge', 'key fob', 'server room',
                    'network plan', 'system architecture', 'technical spec', 'cloud config',
                    'infrastructure config', 'secret key', 'private key', 'public key', 'ssl cert',
                    'ec2', 's3 bucket', 'lambda', 'azure devops', 'github actions', 'jenkins', 'ansible',
                    'nginx', 'apache', 'reverse proxy', 'vlan', 'wan', 'sd-wan', 'pki', 'ipsec', 'radius',
                    'snmp', 'syslog', 'ids', 'ips', 'ddos', 'backup recovery', 'disaster recovery',
                    'rto', 'rpo', 'data center', 'hypervisor', 'vmware', 'hyper-v', 'san', 'nas',
                    'data lake', 'data warehouse', 'etl', 'sql server', 'helm chart', 'container registry',
                    'mfa', 'multi-factor', 'zero trust', 'zero-trust', 'network security',
                ],
                'HR': [
                    'employee', 'payroll', 'talent', 'workforce', 'compensation', 'benefits',
                    'performance review', 'recruiting', 'headcount', 'onboarding', 'hr policy',
                    'human capital', 'retention', 'upskilling', 'organizational', 'staffing',
                    'leave of absence', 'pto', 'paid time off', 'fmla', 'hiring', 'job description',
                    'offer letter', 'severance', 'bonus', '401k', 'health insurance', 'dental', 'vision',
                    'overtime', 'org chart', 'succession planning', 'exit interview', 'attrition',
                    'performance improvement plan', 'corrective action', 'written warning', 'resignation',
                    'background screening', 'drug test', 'w-2', 'cobra', 'fsa', 'hsa',
                    'workers compensation', 'parental leave', 'pay band', 'job grade', 'i-9', 'w-4',
                    'remote work policy', 'direct deposit', 'employee handbook', 'hr investigation',
                    'harassment', 'diversity', 'inclusion', 'equity compensation', 'stock option',
                    'temp worker', 'disciplinary', 'termination', 'background check', 'salary',
                ],
                'Finance and Accounting': [
                    'ebitda', 'balance sheet', 'general ledger', 'gl code', 'accounts payable',
                    'accounts receivable', 'journal entry', 'tax filing', 'fiscal year', 'cash flow',
                    'budget variance', 'income statement', 'revenue recognition', 'audit schedule',
                    'amortization', 'depreciation', 'gross margin', 'net income', 'operating income',
                    'profit and loss', 'p&l', 'working capital', 'capex', 'opex', 'chart of accounts',
                    'cost center', 'trial balance', 'bank reconciliation', 'expense report', 'accrual',
                    'deferred revenue', 'invoice', 'purchase order', 'payment terms', 'ach payment',
                    'tax provision', 'deferred tax', 'tax return', 'gaap', 'ifrs', 'sox compliance',
                    'internal controls', 'financial close', 'month-end close', 'year-end close',
                    'transfer pricing', 'impairment', 'write-off', 'bad debt', 'credit memo',
                    'treasury', 'liquidity', 'line of credit', 'interest expense', 'budget forecast',
                    'financial statement', 'quarterly report', 'annual report', 'tax strategy',
                    'variance analysis', 'margin analysis', 'financial model', 'audit finding',
                    'profit margin', 'financial audit',
                ],
                'Legal + Compliance': [
                    'whereas', 'indemnification', 'governing law', 'jurisdiction', 'litigation',
                    'settlement', 'nda', 'data processing agreement', 'gdpr', 'sox compliance',
                    'pci-dss', 'pci dss', 'hipaa', 'regulatory filing', 'contractual obligation',
                    'force majeure', 'arbitration', 'breach of contract', 'intellectual property',
                    'copyright', 'trademark', 'patent', 'license agreement', 'service agreement',
                    'master services agreement', 'msa', 'statement of work', 'liability',
                    'limitation of liability', 'warranty disclaimer', 'confidentiality', 'non-compete',
                    'non-solicitation', 'injunctive relief', 'termination clause', 'dispute resolution',
                    'data privacy', 'right to erasure', 'privacy policy', 'terms of service',
                    'corporate governance', 'board resolution', 'shareholder agreement', 'due diligence',
                    'data breach', 'consent order', 'cease and desist', 'employment law',
                    'subpoena', 'legal hold', 'e-discovery', 'compliance violation', 'regulatory risk',
                    'representations and warranties', 'in witness whereof', 'executed as of',
                    'indemnify', 'obligor', 'contract amendment', 'addendum', 'exhibit',
                ],
                'Sales & Business Development': [
                    'pipeline', 'deal stage', 'win probability', 'quota', 'go-to-market', 'crm',
                    'opportunity tracking', 'revenue forecast', 'prospect list', 'close rate',
                    'lead generation', 'sales cycle', 'discovery call', 'demo', 'proposal', 'rfp',
                    'request for proposal', 'sales territory', 'account executive', 'business development',
                    'commission', 'sales incentive', 'booking', 'annual recurring revenue', 'arr',
                    'monthly recurring revenue', 'mrr', 'average contract value', 'acv', 'churn',
                    'upsell', 'cross-sell', 'account expansion', 'renewal', 'sales playbook',
                    'battle card', 'win loss', 'sales enablement', 'sales qualified lead',
                    'customer acquisition cost', 'lifetime value', 'net revenue retention',
                    'pipeline report', 'sales target', 'close date', 'opportunity stage',
                    'partner channel', 'reseller', 'go to market', 'rfq', 'bid',
                ],
                'Marketing & Communications': [
                    'brand guidelines', 'marketing campaign', 'social media', 'press release',
                    'content strategy', 'seo', 'audience targeting', 'advertising', 'brand voice',
                    'marketing funnel', 'click-through rate', 'ctr', 'conversion rate', 'cost per click',
                    'cpc', 'return on ad spend', 'roas', 'impressions', 'engagement rate',
                    'email newsletter', 'drip campaign', 'email marketing', 'marketing automation',
                    'hubspot', 'marketo', 'google ads', 'pay-per-click', 'ppc', 'display advertising',
                    'retargeting', 'landing page', 'content calendar', 'whitepaper', 'public relations',
                    'media outreach', 'event marketing', 'webinar', 'brand identity', 'logo usage',
                    'messaging framework', 'positioning statement', 'tagline', 'value proposition',
                    'media kit', 'product launch', 'demand generation', 'brand awareness',
                    'thought leadership', 'influencer', 'earned media', 'paid media', 'content marketing',
                ],
                'Product Development / R&D': [
                    'product roadmap', 'sprint', 'backlog', 'user story', 'mvp', 'minimum viable product',
                    'prototype', 'feature request', 'ux research', 'engineering ticket',
                    'product requirement', 'product spec', 'functional spec', 'design doc',
                    'architecture decision record', 'adr', 'kanban', 'scrum', 'agile', 'epic',
                    'story points', 'velocity', 'release planning', 'product vision', 'innovation',
                    'r&d', 'research and development', 'patent pending', 'proof of concept', 'poc',
                    'technology evaluation', 'design review', 'code review', 'technical debt',
                    'sdk', 'developer documentation', 'integration guide', 'acceptance criteria',
                    'definition of done', 'user acceptance testing', 'uat', 'quality assurance',
                    'bug report', 'issue tracker', 'jira', 'confluence', 'product analytics',
                    'feature flag', 'beta testing', 'design system', 'ux design', 'wireframe',
                    'mockup', 'customer feedback', 'nps survey', 'launch plan', 'release notes',
                ],
                'Operations and Internal Documentation': [
                    'standard operating procedure', 'sop', 'workflow', 'supply chain', 'logistics',
                    'facility management', 'meeting minutes', 'operational kpi', 'process improvement',
                    'vendor management', 'procurement', 'purchase requisition', 'service level agreement',
                    'sla', 'business continuity', 'crisis management', 'risk register', 'risk assessment',
                    'project management', 'project plan', 'gantt chart', 'milestone tracking',
                    'change management', 'internal memo', 'policy document', 'operational review',
                    'capacity planning', 'resource allocation', 'fleet management', 'asset management',
                    'maintenance schedule', 'quality control', 'iso certification', 'six sigma',
                    'lean process', 'continuous improvement', 'kaizen', 'audit trail', 'internal audit',
                    'compliance checklist', 'training material', 'facilities management',
                    'travel policy', 'expense policy', 'vendor scorecard', 'contractor management',
                    'escalation process', 'change request', 'internal report', 'operational efficiency',
                ],
                'Customer / Client Documentation': [
                    'prepared for', 'submitted to', 'engagement summary', 'client onboarding',
                    'account summary', 'customer contact', 'client relationship', 'customer success',
                    'client status', 'project status report', 'client feedback', 'satisfaction survey',
                    'net promoter score', 'customer health score', 'executive business review', 'qbr',
                    'client meeting notes', 'account plan', 'customer journey', 'helpdesk ticket',
                    'service request', 'client briefing', 'engagement letter', 'scope confirmation',
                    'client reference', 'implementation guide', 'handover document', 'customer story',
                    'client profile', 'account review', 'client deliverable', 'weekly update',
                ],
            }

            for grp, keywords in kw_map.items():
                for kw in keywords:
                    if kw in content_lower:
                        scores[grp] += 1

            # Consulting/report filenames get a small client-doc bonus
            if any(x in file_lower for x in ['consulting', 'report', 'engagement', 'deliverable']):
                scores['Customer / Client Documentation'] += 1

            best_grp, best_score = max(scores.items(), key=lambda x: x[1])
            second_score = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0

            if best_score >= 2:
                group = best_grp
                # Higher margin of victory → higher confidence
                margin = best_score - second_score
                confidence = min(0.80, 0.40 + best_score * 0.03 + margin * 0.03)
                reasoning_factors.append(
                    f'Content-keyword scoring: {best_score} hits for "{group}" '
                    f'(runner-up: {second_score})'
                )
            elif best_score == 1:
                group = best_grp
                confidence = 0.40
                reasoning_factors.append(f'Weak content match (1 hit) for "{group}"')
            # else: stays Outliers / Others

        # Adjust confidence based on PII detection strength
        if len(pii_detected) >= 3:
            confidence = min(0.95, confidence + 0.2)  # High confidence with multiple PII types
        elif len(pii_detected) >= 1:
            confidence = min(0.9, confidence + 0.1)   # Boost confidence with any PII

        # Calculate risk score based on sensitivity and PII
        if sensitivity == 'High':
            risk_score = max(risk_score, 7 + len(pii_detected))  # 7-10 range for high sensitivity
        elif sensitivity == 'Moderate':
            risk_score = max(risk_score, 4 + len(pii_detected))  # 4-7 range for moderate
        else:
            risk_score = min(risk_score, 3)  # 0-3 range for low sensitivity
            
        risk_score = min(risk_score, 10)  # Cap at 10

        # Build detailed reasoning
        reasoning = f"Fallback classification for '{file_name}'"
        if reasoning_factors:
            reasoning += f". Key factors: {', '.join(reasoning_factors)}"
        if pii_detected:
            reasoning += f". PII detected: {', '.join(pii_detected)}"
        if not content:
            reasoning += ". Limited to filename analysis only"

        # Build document_summary from what we know about the file
        doc_summary_parts = [f"This document appears to be a {group} record based on its filename and content patterns."]
        if pii_detected:
            doc_summary_parts.append(f"It contains sensitive data including: {', '.join(pii_detected)}.")
        if sensitivity == 'High':
            doc_summary_parts.append("The document is classified as High sensitivity and should be handled with restricted access.")
        elif sensitivity == 'Moderate':
            doc_summary_parts.append("The document contains internal business information and should be treated as confidential.")
        else:
            doc_summary_parts.append("The document contains general business information with no identified PII.")
        document_summary = ' '.join(doc_summary_parts)

        # Build confidential_findings list from detected PII and reasoning factors
        confidential_findings = []
        for factor in reasoning_factors:
            confidential_findings.append(factor)
        if pii_detected:
            for pii_type in pii_detected:
                confidential_findings.append(f"{pii_type} pattern detected in document content")

        return {
            'functional_group': group,
            'sensitivity_level': sensitivity,
            'confidence': round(confidence, 2),
            'functional_group_confidence': round(confidence, 2),
            'sensitivity_confidence': round(confidence, 2),
            'risk_score': risk_score,
            'document_summary': document_summary,
            'confidential_findings': confidential_findings,
            'pii_detected': pii_detected,
            'reasoning': reasoning,
            'classification_status': 'enhanced_fallback',
            'error_message': 'API unavailable; using enhanced heuristic analysis',
            'model_used': 'keyword_fallback',
        }
