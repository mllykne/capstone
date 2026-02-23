"""
SharePoint Scanner Module

High-level interface for scanning and managing SharePoint sites.
Coordinates file scanning, classification, and reporting.
"""

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import logging

from .file_scanner import FileScanner
from .content_extractor import extract_text
from .ai_classifier import AIClassifier

logger = logging.getLogger(__name__)


class SharePointScanner:
    """
    High-level SharePoint scanning and management interface.
    Coordinates file discovery, classification, and reporting.
    """
    
    def __init__(self, demo_root: Path = None):
        """Initialize SharePoint scanner with demo data location."""
        if demo_root is None:
            demo_root = Path(__file__).parent.parent / 'demo_sharepoint'
        
        self.demo_root = demo_root
        self.file_scanner = FileScanner(demo_root)
        self.classifier = AIClassifier()
        self.results = []
        
        # Define SharePoint site mapping
        self.SHAREPOINT_SITES = {
            "Finance Team": self.demo_root / "Finance_Site",
            "HR Department": self.demo_root / "HR_Site",
            "HR Records": self.demo_root / "HR_Department",
            "IT Security": self.demo_root / "IT_Site",
            "IT Systems": self.demo_root / "IT_Systems",
            "Legal Compliance": self.demo_root / "Legal_Site",
            "Client Site": self.demo_root / "Client_Site",
            "Operations Management": self.demo_root / "Operations_Site",
            "Marketing": self.demo_root / "Marketing_Site",
        }
    
    def scan_all_sites(self, verbose: bool = False) -> Dict[str, Any]:
        """
        Scan all SharePoint sites and return summary report.
        
        Args:
            verbose: Whether to include detailed results
            
        Returns:
            Dictionary containing scan results and summary
        """
        logger.info("Starting scan of all SharePoint sites...")
        
        all_documents = []
        site_summaries = {}
        
        for site_name, site_path in self.SHAREPOINT_SITES.items():
            if not site_path.exists():
                logger.warning(f"Site path does not exist: {site_path}")
                continue
                
            site_docs = self._scan_site(site_name, site_path)
            all_documents.extend(site_docs)
            site_summaries[site_name] = len(site_docs)
            
            logger.info(f"Scanned {site_name}: {len(site_docs)} documents")
        
        # Store results
        self.results = all_documents
        
        # Generate summary report
        report = self._generate_scan_summary(all_documents, site_summaries)
        
        logger.info(f"Scan complete. Total documents: {len(all_documents)}")
        return report
    
    def _scan_site(self, site_name: str, site_path: Path) -> List[Dict[str, Any]]:
        """Scan individual SharePoint site."""
        documents = []
        
        try:
            for root, dirs, files in os.walk(site_path):
                for filename in files:
                    if filename.startswith('.'):
                        continue
                        
                    file_path = Path(root) / filename
                    file_ext = file_path.suffix.lower()
                    
                    # Check supported formats
                    if file_ext not in {'.txt', '.pdf', '.docx'}:
                        continue
                    
                    # Get file metadata
                    try:
                        stat = file_path.stat()
                        doc = {
                            'name': filename,
                            'path': str(file_path),
                            'site': site_name,
                            'size_bytes': stat.st_size,
                            'size_mb': round(stat.st_size / (1024 * 1024), 2),
                            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            'extension': file_ext,
                            'status': 'unclassified',
                            'classification': None
                        }
                        documents.append(doc)
                        
                    except Exception as e:
                        logger.error(f"Error processing {file_path}: {e}")
                        
        except Exception as e:
            logger.error(f"Error scanning site {site_name}: {e}")
            
        return documents
    
    def _generate_scan_summary(self, documents: List[Dict], site_summaries: Dict[str, int]) -> Dict[str, Any]:
        """Generate scan summary report."""
        total_docs = len(documents)
        total_size_mb = sum(doc['size_mb'] for doc in documents)
        
        return {
            'total_documents': total_docs,
            'total_size_mb': round(total_size_mb, 2),
            'by_site': site_summaries,
            'by_extension': self._count_by_extension(documents),
            'scanned_at': datetime.now().isoformat(),
            'status': 'completed'
        }
    
    def _count_by_extension(self, documents: List[Dict]) -> Dict[str, int]:
        """Count documents by file extension."""
        counts = {}
        for doc in documents:
            ext = doc['extension']
            counts[ext] = counts.get(ext, 0) + 1
        return counts
    
    def _generate_risk_report(self, classification_data: Dict, verbose: bool = False) -> Dict[str, Any]:
        """
        Generate risk assessment report.
        
        Args:
            classification_data: Classification results (can be empty for demo)
            verbose: Include detailed breakdown
            
        Returns:
            Risk assessment report
        """
        # For demo purposes, generate a basic report structure
        if not self.results:
            return {
                'total_documents_scanned': 0,
                'high_risk_count': 0,
                'high_risk_percentage': '0.0%',
                'pii_detected_count': 0,
                'average_risk_score': 0.0,
                'by_group': {},
                'by_sensitivity': {'Low': 0, 'Moderate': 0, 'High': 0},
                'top_risks': [],
                'generated_at': datetime.now().isoformat()
            }
        
        total_docs = len(self.results)
        
        # Generate sample risk assessment for demo
        sample_groups = [
            'HR', 'Finance and Accounting', 'Legal + Compliance',
            'Customer / Client Documentation', 'IT & Systems'
        ]
        
        by_group = {}
        for i, group in enumerate(sample_groups):
            by_group[group] = max(1, total_docs // len(sample_groups) + (i % 2))
        
        # Sample top risks
        top_risks = []
        for i, doc in enumerate(self.results[:5]):
            top_risks.append({
                'file_name': doc['name'],
                'functional_group': sample_groups[i % len(sample_groups)],
                'sensitivity': ['High', 'Moderate', 'Low'][i % 3],
                'risk_score': round(8.5 - (i * 0.5), 1)
            })
        
        return {
            'total_documents_scanned': total_docs,
            'high_risk_count': max(1, total_docs // 5),
            'high_risk_percentage': f"{(max(1, total_docs // 5) / total_docs * 100):.1f}%",
            'pii_detected_count': max(0, total_docs // 10),
            'average_risk_score': 5.4,
            'by_group': by_group,
            'by_sensitivity': {
                'High': max(1, total_docs // 4),
                'Moderate': max(1, total_docs // 2),
                'Low': max(1, total_docs - total_docs // 4 - total_docs // 2)
            },
            'top_risks': top_risks,
            'sensitive_data_alert': {
                'total_with_pii': max(0, total_docs // 10),
                'types_found': ['SSN', 'Credit Card', 'Email'] if total_docs > 5 else []
            },
            'risk_summary': {
                'critical_risk': [doc for doc in self.results[:2]],
                'high_risk': [doc for doc in self.results[2:5]],
                'medium_risk': [doc for doc in self.results[5:10]]
            },
            'generated_at': datetime.now().isoformat()
        }