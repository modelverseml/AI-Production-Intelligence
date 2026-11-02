import re
import time
from functools import lru_cache
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from app.config import settings
from app.models import Runbook

RRF_K = 60
CANDIDATE_POOL = 20

def tokenize(text):
    return re.findall(r"[a-z0-9_]+", text.lower())

@lru_cache(maxsize=1)
def embedding_model():
    return SentenceTransformer(settings.EMBEDDING_MODEL)

class HybridRetriever:
    """BM25 + dense retrieval fused with reciprocal rank fusion, then reranked."""

    def __init__(self, documents):
        self.documents = documents
        self.corpus = [
            tokenize(doc['text']) for doc in documents
        ]

        self.bm25 = BM25Okapi(self.corpus)
        self.embeddings = embedding_model().encode(
            [doc['text'] for doc in documents],
            normalize_embeddings = True,
            convert_to_numpy = True,
            show_progress_bar = False
        )

    def search(self, query, top_k = 5, exclude_id = None, doc_type = None):
        started = time.perf_counter()
        tokens = tokenize(query)
        bm_scores = self.bm25.get_scores(tokens)

        query_vector = embedding_model().encode(
            [query],
            normalize_embeddings = True,
            convert_to_numpy = True,
            show_progress_bar = False,
        )[0]

        dense_scores = self.embeddings @ query_vector
        bm_rank = np.argsort(-bm_scores)
        dense_rank = np.argsort(-dense_scores)
        fused = np.zeros(len(self.documents), dtype = float)

        # Reciprocal rank fusion over the two rankings.
        for ranking in (bm_rank, dense_rank):
            for rank, idx in enumerate(ranking):
                fused[idx] += 1.0 / (RRF_K + rank + 1)

        # Optionally restrict to one document type (e.g. only runbooks).
        if doc_type is not None:
            for idx, doc in enumerate(self.documents):
                if doc['type'] != doc_type:
                    fused[idx] = 0.0

        fused_norm = fused / max(fused.max(), 1e-9)
        candidate_ids = [
            idx for idx in np.argsort(-fused)[:CANDIDATE_POOL + 1]
            if fused[idx] > 0
        ]
        query_terms = set(tokens)

        # Rerank the fused candidate pool with a lightweight lexical/dense scorer.
        results = []

        for idx in candidate_ids:
            idx = int(idx)
            doc = self.documents[idx]

            if doc['id'] == exclude_id:
                continue
            doc_terms = set(self.corpus[idx])
            overlap = len(query_terms & doc_terms)/max(1, len(query_terms))

            score = (
                0.50 * float(fused_norm[idx])
                + 0.35 * float(dense_scores[idx])
                + 0.15 * overlap
            )
            results.append({
                **{key: value for key, value in doc.items() if key != 'text'},
                "snippet" : doc['text'][:280],
                "score" : round(score, 4),
                "bm25" : round(float(bm_scores[idx]), 3),
                "dense" : round(float(dense_scores[idx]), 3),
            })

        results.sort(
            key = lambda item : item['score'],
            reverse=True
        )

        latency_ms = (
            time.perf_counter() - started
        )*1000

        return {
            "documents" : results[:top_k],
            "latency_ms" : round(latency_ms,2)
        }


def build_documents(db):
    """Runbook documents for hybrid retrieval."""
    return [
        {
            "id" : runbook.code,
            "type" : "runbook",
            "title" : runbook.title,
            "category" : runbook.category,
            "text" : f"{runbook.title}. {runbook.body}",
        }
        for runbook in db.query(Runbook).order_by(Runbook.id).all()
    ]
