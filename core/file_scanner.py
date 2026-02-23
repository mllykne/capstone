"""
File Scanner Module

Responsible for discovering documents in the simulated SharePoint folder structure.
Does NOT read file contents - only identifies files and basic metadata.

Scans data/simulated_sharepoint/ recursively and returns:
- File paths
- File sizes
- Modified dates
- Supported formats only (.pdf, .docx, .xlsx, .pptx, .txt)
"""

import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple
import logging

logger = logging.getLogger(__name__)


class FileScanner:
    """
    Scans simulated SharePoint folder structure.
    Returns file metadata without reading content.
    """

    SUPPORTED_FORMATS = {'.pdf', '.docx', '.xlsx', '.pptx', '.txt'}

    def __init__(self, sharepoint_path: str):
        """
        Initialize scanner with path to simulated SharePoint.

        Args:
            sharepoint_path: Root path to simulated SharePoint folder
        """
        self.sharepoint_path = Path(sharepoint_path)
        if not self.sharepoint_path.exists():
            raise FileNotFoundError(f"SharePoint path does not exist: {sharepoint_path}")

    def scan_all(self) -> List[Dict]:
        """
        Recursively scan entire SharePoint structure.

        Returns:
            List of document metadata dicts containing:
            - file_name: Original filename
            - file_path: Absolute file path
            - file_size: File size in bytes
            - modified_date: Datetime of last modification
            - file_extension: File extension
            - folder_category: Category folder (HR, Finance, etc.)
        """
        documents = []
        for root, dirs, files in os.walk(self.sharepoint_path):
            for filename in files:
                # Check if file has supported format
                file_ext = Path(filename).suffix.lower()
                if file_ext not in self.SUPPORTED_FORMATS:
                    continue

                file_path = Path(root) / filename
                try:
                    stat = file_path.stat()
                    modified_date = datetime.fromtimestamp(stat.st_mtime)

                    doc_meta = {
                        'file_name': filename,
                        'file_path': str(file_path),
                        'file_size': stat.st_size,
                        'modified_date': modified_date,
                        'file_extension': file_ext,
                        'folder_category': self._extract_category(root),
                    }
                    documents.append(doc_meta)
                    logger.info(f"Discovered: {filename}")
                except Exception as e:
                    logger.error(f"Error scanning {file_path}: {e}")

        logger.info(f"Scan complete. Found {len(documents)} documents.")
        return documents

    def scan_folder(self, folder_name: str) -> List[Dict]:
        """
        Scan specific category folder (e.g., 'HR', 'Finance').

        Args:
            folder_name: Category folder name

        Returns:
            List of document metadata dicts for that folder
        """
        folder_path = self.sharepoint_path / folder_name
        if not folder_path.exists():
            logger.warning(f"Folder does not exist: {folder_path}")
            return []

        documents = []
        for filename in os.listdir(folder_path):
            file_path = folder_path / filename
            if not file_path.is_file():
                continue

            file_ext = Path(filename).suffix.lower()
            if file_ext not in self.SUPPORTED_FORMATS:
                continue

            try:
                stat = file_path.stat()
                modified_date = datetime.fromtimestamp(stat.st_mtime)

                doc_meta = {
                    'file_name': filename,
                    'file_path': str(file_path),
                    'file_size': stat.st_size,
                    'modified_date': modified_date,
                    'file_extension': file_ext,
                    'folder_category': folder_name,
                }
                documents.append(doc_meta)
            except Exception as e:
                logger.error(f"Error scanning {file_path}: {e}")

        return documents

    def _extract_category(self, path: str) -> str:
        """
        Extract functional category from folder path.

        Args:
            path: Full file path

        Returns:
            Category name (HR, Finance, etc.) or 'Unknown'
        """
        relative = Path(path).relative_to(self.sharepoint_path)
        parts = relative.parts
        if parts:
            return parts[0]
        return 'Unknown'


def get_file_count(sharepoint_path: str) -> Dict[str, int]:
    """
    Quick utility to count documents by category.

    Args:
        sharepoint_path: Root path to simulated SharePoint

    Returns:
        Dict with category names and document counts
    """
    scanner = FileScanner(sharepoint_path)
    documents = scanner.scan_all()
    counts = {}
    for doc in documents:
        category = doc['folder_category']
        counts[category] = counts.get(category, 0) + 1
    return counts
