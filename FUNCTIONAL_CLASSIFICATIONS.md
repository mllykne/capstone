# The 10 Functional Classifications
## What Goes in Each Bucket

---

## 1. HR (Human Resources)
**What belongs here:** Documents about managing people inside the organisation.
- Payroll records and reconciliation reports
- Employee salary and compensation plans
- Performance reviews and improvement plans (PIPs)
- Benefits enrollment forms
- Background check reports
- Recruiting, onboarding, and offboarding materials
- Disciplinary notices and termination records
- Org charts and headcount reports
- HR policy documents (leave policy, conduct policy)
- Training records and certifications

**Key signals:** SSNs, Employee IDs, salary figures, "performance review", "base pay", "direct deposit"

---

## 2. Finance and Accounting
**What belongs here:** Documents about money movement, financial reporting, and accounting records.
- General ledger extracts and journal entries
- Budget forecasts and variance analyses
- Revenue recognition memos
- Tax filings and tax provisions
- Accounts payable / accounts receivable reports
- Bank statements and cash flow statements
- Income statements and balance sheets
- Financial audit schedules
- Expense reports and invoice records

**Key signals:** GL codes, EBITDA, "accounts payable", routing numbers, bank account numbers, fiscal year references

---

## 3. Legal + Compliance
**What belongs here:** Documents with binding legal obligations or regulatory requirements.
- NDAs and confidentiality agreements
- Master Service Agreements (MSAs) and contracts
- Data Processing Agreements (DPAs)
- Employment contracts
- Settlement agreements and litigation memos
- Regulatory filings and compliance certifications
- Internal compliance policies (GDPR, SOX, HIPAA, PCI-DSS)
- Privacy notices and data handling policies
- Legal opinions and risk assessments

**Key signals:** "Whereas", "indemnification", "governing law", jurisdiction references, regulatory framework names (GDPR, SOX, HIPAA)

---

## 4. Customer / Client Documentation
**What belongs here:** Client-facing deliverables where *no single functional domain dominates*. This is a narrow catch-all for relationship management content only.
- Client account summaries and status reports
- Onboarding packs sent to clients
- Engagement letters and scope-of-work documents
- Project milestone progress summaries
- Customer contact records
- Case studies and client executive summaries
- Meeting notes that are purely about relationship management

> **Critical rule:** A consulting report *about IT infrastructure* goes to **IT & Systems**. A report *about HR strategy* goes to **HR**. Only use this bucket when the document has no dominant functional subject.

---

## 5. Sales & Business Development
**What belongs here:** Documents about generating revenue and tracking deals.
- Sales pipeline reports and CRM exports
- Pricing proposals and discount structures
- Go-to-market strategy documents
- Win/loss analyses
- Partnership proposals and term sheets
- Sales forecasts and quota plans
- Opportunity tracking records
- Prospect lists and contact databases

**Key signals:** "deal stage", "win probability", "pipeline", "close rate", "quota"

---

## 6. Marketing & Communications
**What belongs here:** External messaging, branding, and campaign content.
- Press releases and media statements
- Marketing campaign strategies and briefs
- Social media plans and content calendars
- Brand guidelines and style guides
- Website copy and content drafts
- Advertising creative briefs
- Audience targeting and segmentation analyses
- SEO strategies and performance reports

**Key signals:** "brand voice", "campaign", "press release", "audience targeting", "content strategy"

---

## 7. IT & Systems
**What belongs here:** Technology infrastructure, cloud, security, and systems documentation.
- Cloud infrastructure configs (AWS, Azure, GCP)
- VPN credentials and remote access instructions
- Network topology and architecture diagrams
- Access control matrices and IAM policies
- Firewall rules and DNS records
- Server inventory and database server configs
- Kubernetes / Docker / Terraform specs
- CI/CD pipeline documentation
- SSL certificates and encryption key management
- Security incident response procedures
- API documentation and integration specs
- Building security codes and physical access credentials

**Key signals:** IP addresses, API keys, SSH keys, cloud provider names, port numbers, "subnet", "terraform", "kubernetes"

---

## 8. Product Development / R&D
**What belongs here:** Documents about building products and conducting research.
- Product roadmaps and feature prioritisation
- Sprint backlogs and engineering tickets
- User stories and acceptance criteria
- Prototype specifications and design mockups
- A/B test plans and UX research findings
- R&D research reports
- Technical architecture decisions (product-level, not infra)
- MVP definitions and release plans

**Key signals:** "sprint", "backlog", "user story", "roadmap", "MVP", "prototype", "feature request"

---

## 9. Operations and Internal Documentation
**What belongs here:** Internal process documentation not specific to any other department.
- Standard Operating Procedures (SOPs)
- Internal policy manuals
- Workflow and process descriptions
- Meeting minutes (internal, operational)
- Facility and supply chain documentation
- Logistics and vendor management procedures
- Operational KPI reports
- Process improvement plans

**Key signals:** "SOP", "standard operating procedure", "workflow", "supply chain", "meeting minutes", "process improvement"

---

## 10. Outliers / Others
**What belongs here:** Documents that genuinely cannot be classified into any of the above 9 groups.
- Blank or corrupted files
- Completely generic templates with zero business context
- Unrecognisable file contents

> This bucket should be used as a last resort only. If there is *any* discernible business purpose in a document, it belongs in one of the first 9 groups. In practice this category should represent <2% of a real document library.

---

## Quick Decision Guide

```
Does it contain SSNs / payroll / salary / employee IDs?  →  HR
Does it contain account numbers / GL codes / tax filings? →  Finance
Does it contain contracts / legal clauses / regulations?  →  Legal
Does it contain server configs / API keys / cloud infra?  →  IT & Systems
Does it contain deal stages / pipeline / pricing?         →  Sales
Does it contain product roadmaps / sprint backlogs?       →  Product / R&D
Does it contain brand guidelines / campaigns / press?     →  Marketing
Does it contain SOPs / meeting minutes / procedures?      →  Operations
Is it a client deliverable with NO dominant domain above? →  Customer/Client
None of the above and truly unclassifiable?               →  Outliers
```

---

## Sensitivity Levels at a Glance

| Level | What Triggers It |
|---|---|
| **High** | SSNs, bank account numbers, credit card numbers, routing numbers, API keys, passwords, wire transfer details, HIPAA/PHI data, employment contracts with salary, litigation documents |
| **Moderate** | Internal strategy docs, client contact info (name/email/phone only), budget forecasts without account numbers, performance reviews without IDs, pricing models, internal meeting notes |
| **Low** | Public-facing marketing content, generic SOPs, press releases, published policies, training materials with no sensitive examples |
