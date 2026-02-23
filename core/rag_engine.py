"""
Retrieval-Augmented Generation (RAG) Engine

Lightweight RAG layer that:
1. Loads knowledge base of functional groups
2. Creates embeddings for group descriptions
3. Embeds incoming document text
4. Calculates semantic similarity
5. Retrieves top 2 closest functional groups with context

Used to improve classification consistency and provide context to Gemini classifier.
"""

import json
import os
from pathlib import Path
from typing import List, Tuple, Dict, Optional


class RAGEngine:
    """
    Lightweight RAG engine for functional group retrieval.
    Uses simple embedding-based similarity search.
    """
    
    def __init__(self, knowledge_base_path: str = None):
        """
        Initialize RAG engine with knowledge base.
        
        Args:
            knowledge_base_path (str): Path to knowledge_base.json. 
                                       Defaults to project root if not specified.
        """
        self.knowledge_base_path = knowledge_base_path or self._find_knowledge_base()
        self.knowledge_base = None
        self.groups = {}
        self.embeddings = {}
        
        # Try to import embeddings library
        self.embedding_model = None
        self._init_embeddings()
        
        # Load knowledge base
        self._load_knowledge_base()
    
    def _find_knowledge_base(self) -> str:
        """Find knowledge_base.json in project root."""
        project_root = Path(__file__).parent.parent
        kb_path = project_root / "knowledge_base.json"
        
        if not kb_path.exists():
            raise FileNotFoundError(
                f"knowledge_base.json not found at {kb_path}. "
                f"Expected location: {project_root}"
            )
        
        return str(kb_path)
    
    def _init_embeddings(self):
        """Initialize embedding model. Try sentence-transformers first, fall back to TF-IDF."""
        try:
            from sentence_transformers import SentenceTransformer
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
            self.embedding_method = 'sentence-transformers'
            print("[OK] Initialized embeddings with sentence-transformers")
        except ImportError:
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer
                self.vectorizer = TfidfVectorizer(max_features=200, stop_words='english')
                self.embedding_method = 'tfidf'
                print("[OK] Initialized embeddings with TF-IDF (fallback)")
            except ImportError:
                self.embedding_method = 'keyword'
                print("[WARN] No embedding library available, using keyword matching (fallback)")
    
    def _load_knowledge_base(self):
        """Load and parse knowledge base JSON."""
        with open(self.knowledge_base_path, 'r') as f:
            self.knowledge_base = json.load(f)
        
        # Build groups dictionary for quick access
        for group in self.knowledge_base['functional_groups']:
            group_id = group['id']
            self.groups[group_id] = group
        
        # Create embeddings for all group descriptions
        self._create_group_embeddings()
        
        print(f"[OK] Loaded {len(self.groups)} functional groups from knowledge base")
    
    def _create_group_embeddings(self):
        """Create embeddings for each functional group description."""
        if self.embedding_method == 'sentence-transformers':
            # Use sentence-transformers for semantic embeddings
            descriptions = [
                group['description'] for group in self.groups.values()
            ]
            embeddings = self.embedding_model.encode(descriptions)
            
            for idx, group in enumerate(self.groups.values()):
                self.embeddings[group['id']] = embeddings[idx]
        
        elif self.embedding_method == 'tfidf':
            # Use TF-IDF vectorizer
            descriptions = [
                group['description'] for group in self.groups.values()
            ]
            embeddings = self.vectorizer.fit_transform(descriptions)
            
            for idx, group in enumerate(self.groups.values()):
                self.embeddings[group['id']] = embeddings[idx]
        
        # keyword method doesn't pre-compute embeddings
    
    def retrieve(
        self, 
        document_text: str, 
        top_k: int = 2
    ) -> List[Dict]:
        """
        Retrieve top-k most relevant functional groups for document.
        
        Args:
            document_text (str): Extracted text from document
            top_k (int): Number of results to return (default: 2)
        
        Returns:
            List[Dict]: Top-k groups with similarity scores and context
                Format: [
                    {
                        'group_id': int,
                        'name': str,
                        'description': str,
                        'keywords': List[str],
                        'document_types': List[str],
                        'similarity_score': float,
                        'matched_keywords': List[str],
                        'context': str
                    },
                    ...
                ]
        
        Example:
            results = rag_engine.retrieve(document_text, top_k=2)
            for result in results:
                print(f"{result['name']}: {result['similarity_score']}")
        """
        # Limit text to first 2000 chars for performance
        text_sample = document_text[:2000].lower()
        
        # Calculate similarity for each group
        similarities = []
        
        if self.embedding_method == 'sentence-transformers':
            similarities = self._calculate_similarity_embedding(text_sample)
        elif self.embedding_method == 'tfidf':
            similarities = self._calculate_similarity_tfidf(text_sample)
        else:
            similarities = self._calculate_similarity_keyword(text_sample)
        
        # Sort by similarity score and get top-k
        sorted_groups = sorted(
            similarities, 
            key=lambda x: x['similarity_score'], 
            reverse=True
        )[:top_k]
        
        return sorted_groups
    
    def _calculate_similarity_embedding(self, text: str) -> List[Dict]:
        """Calculate similarity using semantic embeddings."""
        try:
            import numpy as np
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            # Fallback to keyword method if numpy/sklearn unavailable
            return self._calculate_similarity_keyword(text)
        
        # Embed document text
        doc_embedding = self.embedding_model.encode([text])[0]
        
        similarities = []
        for group_id, group in self.groups.items():
            group_embedding = self.embeddings[group_id]
            
            # Calculate cosine similarity
            score = cosine_similarity(
                [doc_embedding], 
                [group_embedding]
            )[0][0]
            
            matched_keywords = self._find_matched_keywords(text, group)
            
            similarities.append({
                'group_id': group_id,
                'name': group['name'],
                'description': group['description'],
                'keywords': group['keywords'],
                'document_types': group['document_types'],
                'similarity_score': float(score),
                'matched_keywords': matched_keywords,
                'context': self._build_context(group, matched_keywords)
            })
        
        return similarities
    
    def _calculate_similarity_tfidf(self, text: str) -> List[Dict]:
        """Calculate similarity using TF-IDF vectors."""
        try:
            from sklearn.metrics.pairwise import cosine_similarity
        except ImportError:
            return self._calculate_similarity_keyword(text)
        
        # Transform document text
        doc_vector = self.vectorizer.transform([text])
        
        similarities = []
        for group_id, group in self.groups.items():
            group_vector = self.embeddings[group_id]
            
            # Calculate cosine similarity
            score = cosine_similarity(doc_vector, group_vector)[0][0]
            
            matched_keywords = self._find_matched_keywords(text, group)
            
            similarities.append({
                'group_id': group_id,
                'name': group['name'],
                'description': group['description'],
                'keywords': group['keywords'],
                'document_types': group['document_types'],
                'similarity_score': float(score),
                'matched_keywords': matched_keywords,
                'context': self._build_context(group, matched_keywords)
            })
        
        return similarities
    
    def _calculate_similarity_keyword(self, text: str) -> List[Dict]:
        """Calculate similarity using keyword matching (fallback method)."""
        similarities = []
        
        for group_id, group in self.groups.items():
            matched_keywords = self._find_matched_keywords(text, group)
            
            # Calculate score based on keyword matches
            keyword_score = len(matched_keywords) / max(len(group['keywords']), 1)
            
            # Also check description keywords
            description_lower = group['description'].lower()
            description_keywords = [
                kw for kw in group['keywords'] 
                if kw.lower() in text
            ]
            
            # Weighted score: 70% keywords, 30% description
            score = (keyword_score * 0.7) + (
                len(description_keywords) / max(len(group['keywords']), 1) * 0.3
            )
            
            similarities.append({
                'group_id': group_id,
                'name': group['name'],
                'description': group['description'],
                'keywords': group['keywords'],
                'document_types': group['document_types'],
                'similarity_score': min(score, 1.0),
                'matched_keywords': matched_keywords,
                'context': self._build_context(group, matched_keywords)
            })
        
        return similarities
    
    def _find_matched_keywords(self, text: str, group: Dict) -> List[str]:
        """Find keywords from group that appear in text."""
        matched = []
        for keyword in group['keywords']:
            if keyword.lower() in text:
                matched.append(keyword)
        
        return matched[:5]  # Return top 5 matched keywords
    
    def _build_context(self, group: Dict, matched_keywords: List[str]) -> str:
        """Build context string for classification prompt."""
        context_parts = [
            f"Group: {group['name']}",
            f"Description: {group['description']}",
        ]
        
        if matched_keywords:
            context_parts.append(f"Matched keywords: {', '.join(matched_keywords)}")
        
        # Include top 3 document types
        doc_types = group['document_types'][:3]
        context_parts.append(f"Example documents: {', '.join(doc_types)}")
        
        return "\n".join(context_parts)
    
    def get_all_groups(self) -> Dict:
        """
        Get all functional groups.
        
        Returns:
            Dict: All functional groups indexed by ID
        """
        return self.groups
    
    def get_group(self, group_id: int) -> Optional[Dict]:
        """
        Get specific functional group by ID.
        
        Args:
            group_id (int): Group ID (1-10)
        
        Returns:
            Dict: Group information or None if not found
        """
        return self.groups.get(group_id)
    
    def build_rag_context(self, document_text: str, top_k: int = 2) -> str:
        """
        Build RAG context string for classification prompt.
        
        Args:
            document_text (str): Document text
            top_k (int): Number of groups to include (default: 2)
        
        Returns:
            str: Formatted context for Gemini prompt
        
        Example:
            context = rag_engine.build_rag_context(doc_text)
            prompt = f"Classify this document.\\n\\n{context}\\n\\nText: {doc_text}"
        """
        results = self.retrieve(document_text, top_k=top_k)
        
        context_lines = [
            "=== RETRIEVED FUNCTIONAL GROUP GUIDANCE ===\n"
        ]
        
        for idx, result in enumerate(results, 1):
            context_lines.append(
                f"{idx}. {result['name']} (Similarity: {result['similarity_score']:.2f})"
            )
            context_lines.append(f"   {result['context']}\n")
        
        return "\n".join(context_lines)


# Standalone functions for simple usage
def retrieve_context(document_text: str, top_k: int = 2) -> str:
    """
    Simple function to retrieve RAG context for a document.
    
    Args:
        document_text (str): Document text to classify
        top_k (int): Number of groups to retrieve
    
    Returns:
        str: RAG context formatted for prompt
    
    Example:
        context = retrieve_context(document_text)
        print(context)
    """
    engine = RAGEngine()
    return engine.build_rag_context(document_text, top_k=top_k)


if __name__ == "__main__":
    # CLI for testing RAG engine
    import sys
    
    print("Initializing RAG Engine...\n")
    engine = RAGEngine()
    
    # Test with sample documents
    test_docs = [
        "Employee salary reconciliation Q4 report with SSN and compensation details",
        "Revenue recognition memo discussing tax provisions and financial forecasts",
        "Data Protection Agreement GDPR compliance requirements for vendor",
        "Customer project status report with implementation timeline"
    ]
    
    print("Testing RAG retrieval...\n")
    print("=" * 80)
    
    for idx, test_doc in enumerate(test_docs, 1):
        print(f"\nTest Document {idx}:")
        print(f"  Text: {test_doc[:60]}...\n")
        
        results = engine.retrieve(test_doc, top_k=2)
        
        for rank, result in enumerate(results, 1):
            print(f"  {rank}. {result['name']}")
            print(f"     Score: {result['similarity_score']:.3f}")
            print(f"     Keywords: {', '.join(result['matched_keywords'][:3])}")
        
        print("-" * 80)
    
    print("\n✓ RAG Engine test complete")
