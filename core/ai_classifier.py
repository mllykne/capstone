"""
AI Classifier Module

Calls Gemini API to classify documents into functional groups and sensitivity levels.
Handles API communication, retries, and error handling.

Input: Document content + embeddings + metadata
Output: Functional group, sensitivity level, confidence, reasoning
"""

import logging
import json
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

        # Let _build_prompt handle truncation (8000 chars) so we pass full content
        prompt = self._build_prompt(content, file_name, file_size)

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

                # Parse response
                result = self._parse_response(response.text)
                result['classification_status'] = 'success'
                return result

            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                else:
                    logger.error(f"All retries exhausted for {file_name}")
                    return self._fallback_classification(file_name, content)

    def _build_prompt(self, content: str, file_name: str, file_size: int = None) -> str:
        """Build Gemini prompt for classification with enhanced sensitivity analysis and PII detection."""
        sensitivity_str = ', '.join(self.SENSITIVITY_LEVELS)
        
        # Increase content limit and add truncation notice
        max_content = 8000
        content_truncated = False
        if len(content) > max_content:
            content = content[:max_content]
            content_truncated = True

        prompt = f"""You are a document classification expert with deep knowledge of business records and data governance. Analyze the following document and classify it into ONE of the 10 functional groups below.

ENHANCED SENSITIVITY CLASSIFICATION LOGIC:

HIGH SENSITIVITY - Document contains ANY of:
- Personal identifiers: SSNs (###-##-#### format), employee IDs with personal data, passport numbers, driver's license numbers
- Financial data: Bank account numbers, credit card numbers (16 digits), investment account numbers, routing numbers
- Contracts with legal liability: indemnification clauses, settlement amounts, litigation exposure
- Protected health information: medical records, patient IDs, health insurance information
- Security credentials: API keys, passwords, encryption keys, database connection strings, access tokens
- Regulated data: GDPR-protected personal data, HIPAA-covered information, PCI-DSS payment data
- Executive information: C-level compensation, board materials, strategic acquisition plans
- Legal matters: litigation documents, settlement agreements, regulatory violation notices

MODERATE SENSITIVITY - Document contains:
- Internal business plans or confidential strategies
- Client contact information (names, emails, phone numbers)
- Pricing models, discount structures, or competitive pricing
- Performance reviews (without personal identifiers)
- Internal competitive analysis or market intelligence
- Financial forecasts or budget planning (not actual account numbers)
- Employee organizational charts or reporting structures
- Internal security procedures (without actual credentials)
- Vendor contracts or procurement agreements
- Internal meeting notes with business-sensitive discussions

LOW SENSITIVITY - Document contains:
- Public-facing marketing content or press releases
- Generic standard operating procedures (SOPs)
- Published materials or external communications
- General training documentation without sensitive examples
- Public news, announcements, or industry information
- Non-confidential policy documents
- General process documentation

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
{"- Content truncated: Document exceeds 8000 characters, showing first 8000" if content_truncated else ""}

DOCUMENT CONTENT:{" (first 8000 chars)" if content_truncated else ""}
{content}

ENHANCED CLASSIFICATION INSTRUCTIONS:
1. Read the entire content carefully, scanning for ALL PII patterns and sensitive data indicators
2. For each PII type found, note the EXACT text or pattern (e.g., "Found SSN: 123-45-6789 in employee record section")
3. Check against ENHANCED SENSITIVITY CLASSIFICATION LOGIC to determine sensitivity level
4. Identify the PRIMARY SUBJECT MATTER of the document — what field or discipline is this document fundamentally about?
5. Apply PRIORITY ORDER: classify by primary subject matter first (IT, HR, Finance, Legal, Product, Sales, Marketing, Operations) before considering delivery format
6. Only use "Customer / Client Documentation" for documents whose primary subject is client relationship management, generic engagement tracking, or mixed-topic deliverables with no dominant functional discipline
7. Apply DISAMBIGUATION RULES — consulting/advisory documents are classified by WHAT they cover, not by WHO they were written for
8. MUST classify to ONE of the first 9 groups — avoid "Outliers / Others" unless absolutely impossible (blank, corrupted, or zero business context)
9. If content is unclear, choose the CLOSEST match from groups 1-9 based on document purpose or context
10. Provide TWO confidence scores: functional_group_confidence (0.0-1.0) and sensitivity_confidence (0.0-1.0)
11. Be strict with sensitivity: High only if regulated/PII data present; Moderate for internal business info; Low for public content
12. Calculate risk_score (0-10): High sensitivity + multiple PII types = 8-10; High sensitivity + some PII = 6-8; Moderate = 3-6; Low = 0-3
13. Provide detailed reasoning with SPECIFIC CITATIONS from the document content

RESPONSE FORMAT REQUIREMENTS:
- Format: JSON only (no markdown, no code blocks, no explanations outside JSON)
- PII Citations: For each PII type found, include specific examples or patterns detected
- Reasoning: Must quote specific text from document and explain classification logic step by step
- Risk Score: Justify the score based on sensitivity level and PII quantity/types

RESPOND IN JSON FORMAT ONLY:
{{
  "functional_group": "<one of the first 9 groups - avoid Outliers unless impossible>",
  "functional_group_confidence": <0.0-1.0>,
  "sensitivity_level": "<Low|Moderate|High>", 
  "sensitivity_confidence": <0.0-1.0>,
  "risk_score": <0-10 numeric score>,
  "document_summary": "<2-3 sentence plain-English overview: what this document is, what information it contains, and its apparent purpose within the organization>",
  "confidential_findings": ["<specific finding 1: describe exactly what sensitive/confidential item was found, e.g. 'SSN 123-45-6789 belonging to John Smith on line 3'>", "<specific finding 2>"],
  "pii_detected": ["<list of specific PII types with examples: e.g., 'SSN: 123-45-6789', 'Credit Card: 4532-****-****-1234'>"],
  "reasoning": "<DETAILED explanation with specific document quotes. Example: 'Classified as HR/High because document contains employee SSN (123-45-6789 in line 5) and salary information ($85,000 annual). Key indicators: employee performance review language, benefits enrollment section, and personal identifiers throughout.'>"
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
            sensitivity = 'High' if pii_detected or any(x in content_lower for x in ['account', 'bank', 'credit']) else 'Moderate'
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
                    'cloud', 'aws', 'azure', 'gcp', 'google cloud', 'kubernetes', 'docker',
                    'microservice', 'terraform', 'infrastructure', 'architecture',
                    'zero-trust', 'zero trust', 'api gateway', 'api management',
                    'devops', 'ci/cd', 'cicd', 'deployment', 'container', 'serverless',
                    'postgresql', 'mongodb', 'redis', 'dynamodb', 'elasticsearch',
                    'hashicorp', 'vault', 'waf', 'edr', 'firewall', 'vpn',
                    'react', 'typescript', 'technology stack', 'tech stack',
                    'digital transformation', 'digital maturity', 'cloud-native',
                    'cloud migration', 'legacy system', 'shadow application',
                    'microservices', 'blue-green', 'strangler pattern',
                    'frontend', 'backend', 'database server', 'load balancer',
                    # credentials / access / network admin
                    'api key', 'api keys', 'access token', 'bearer token', 'refresh token',
                    'oauth', 'authentication', 'authorization', 'credential', 'credentials',
                    'password', 'passphrase', 'network administration', 'network admin',
                    'remote access', 'remote desktop', 'rdp', 'ssh', 'ssl', 'tls',
                    'certificate', 'ldap', 'active directory', 'iam', 'service account',
                    'access control', 'network topology', 'subnet', 'ip address', 'dns',
                    'patch management', 'vulnerability', 'penetration test', 'security audit',
                    'incident response', 'siem', 'intrusion detection', 'endpoint security',
                ],
                'HR': [
                    'employee', 'payroll', 'talent', 'workforce', 'compensation',
                    'benefits', 'performance review', 'recruiting', 'headcount',
                    'training program', 'onboarding', 'hr policy', 'human capital',
                    'retention package', 'upskilling', 'organizational', 'staffing',
                ],
                'Finance and Accounting': [
                    'ebitda', 'balance sheet', 'general ledger', 'gl code',
                    'accounts payable', 'accounts receivable', 'journal entry',
                    'tax filing', 'fiscal year', 'profit margin', 'cash flow',
                    'financial audit', 'budget variance', 'income statement',
                ],
                'Legal + Compliance': [
                    'whereas', 'indemnification', 'governing law', 'jurisdiction',
                    'litigation', 'settlement', 'nda', 'data processing agreement',
                    'gdpr', 'sox compliance', 'pci-dss', 'hipaa', 'regulatory filing',
                    'contractual obligation', 'force majeure', 'arbitration',
                ],
                'Sales & Business Development': [
                    'pipeline', 'deal stage', 'win probability', 'quota',
                    'go-to-market', 'sales cycle', 'close rate', 'crm',
                    'opportunity tracking', 'revenue forecast', 'prospect list',
                ],
                'Marketing & Communications': [
                    'brand guidelines', 'marketing campaign', 'social media plan',
                    'press release', 'content strategy', 'seo', 'audience targeting',
                    'advertising', 'brand voice', 'messaging framework',
                ],
                'Product Development / R&D': [
                    'product roadmap', 'sprint', 'backlog', 'user story', 'mvp',
                    'prototype', 'feature request', 'a/b test', 'ux research',
                    'product requirement', 'engineering ticket',
                ],
                'Operations and Internal Documentation': [
                    'standard operating procedure', 'sop', 'workflow', 'vendor scorecard',
                    'supply chain', 'logistics', 'facility management',
                    'meeting minutes', 'operational kpi', 'process improvement',
                ],
                'Customer / Client Documentation': [
                    'prepared for', 'submitted to', 'engagement summary',
                    'client onboarding', 'account summary', 'customer contact',
                    'client relationship', 'customer success',
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
        }
