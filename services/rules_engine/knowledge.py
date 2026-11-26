from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

POLICIES_PATH = (
    Path(__file__).resolve().parents[2] / "knowledge" / "synthetic_policy_samples" / "policies.json"
)
RATE_CARDS_PATH = (
    Path(__file__).resolve().parents[2] / "knowledge" / "synthetic_policy_samples" / "rate_cards.json"
)

TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


class HybridPolicyRetriever:
    """Hybrid keyword + TF-IDF cosine vector retriever over approved policy wordings."""

    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = json.loads(POLICIES_PATH.read_text(encoding="utf-8"))
        self.chunks: list[dict[str, Any]] = []
        for doc in self.documents:
            for clause in doc["clauses"]:
                self.chunks.append(
                    {
                        "document_id": doc["document_id"],
                        "uin": doc["uin"],
                        "product_name": doc["product_name"],
                        "clause_id": clause["clause_id"],
                        "section": clause["section"],
                        "page": clause["page"],
                        "title": clause["title"],
                        "text": clause["text"],
                        "tokens": _tokenize(f"{clause['title']} {clause['section']} {clause['text']}"),
                    }
                )
        self._idf = self._compute_idf()

    def _compute_idf(self) -> dict[str, float]:
        n = len(self.chunks)
        df: Counter[str] = Counter()
        for c in self.chunks:
            for tok in set(c["tokens"]):
                df[tok] += 1
        return {tok: math.log((n + 1) / (freq + 1)) + 1.0 for tok, freq in df.items()}

    def _tfidf_vec(self, tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        total = max(len(tokens), 1)
        return {tok: (cnt / total) * self._idf.get(tok, 1.0) for tok, cnt in tf.items()}

    @staticmethod
    def _cosine(v1: dict[str, float], v2: dict[str, float]) -> float:
        common = set(v1.keys()) & set(v2.keys())
        num = sum(v1[k] * v2[k] for k in common)
        d1 = math.sqrt(sum(val * val for val in v1.values()))
        d2 = math.sqrt(sum(val * val for val in v2.values()))
        if d1 == 0 or d2 == 0:
            return 0.0
        return num / (d1 * d2)

    def search(
        self, query: str, *, document_ids: list[str] | None = None, top_k: int = 4
    ) -> list[dict[str, Any]]:
        q_tokens = _tokenize(query)
        q_set = set(q_tokens)
        q_vec = self._tfidf_vec(q_tokens)

        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in self.chunks:
            if document_ids and chunk["document_id"] not in document_ids:
                continue
            c_vec = self._tfidf_vec(chunk["tokens"])
            vec_score = self._cosine(q_vec, c_vec)
            kw_overlap = len(q_set & set(chunk["tokens"])) / max(len(q_set), 1)
            hybrid_score = 0.65 * vec_score + 0.35 * kw_overlap
            scored.append((hybrid_score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        results = []
        for score, chunk in scored[:top_k]:
            results.append(
                {
                    "document_id": chunk["document_id"],
                    "uin": chunk["uin"],
                    "clause_id": chunk["clause_id"],
                    "section": chunk["section"],
                    "page": chunk["page"],
                    "title": chunk["title"],
                    "text": chunk["text"],
                    "score": round(score, 4),
                    "reference": f"{chunk['document_id']} {chunk['clause_id']} p.{chunk['page']}",
                }
            )
        return results


def load_rate_card() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(RATE_CARDS_PATH.read_text(encoding="utf-8"))
    return data
