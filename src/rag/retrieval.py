"""FAISS cosine + Kiwi BM25. 각각 top-5를 RRF(k=60)로 결합한다."""

import argparse
import json
import os
import re
import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

from src.config import EMBEDDING_MODEL
from src.rag.documents import DATA_DIR, GROUPS, TOP_K, fingerprint, normalize_text

INDEX_DIR = DATA_DIR / "index"
RRF_K = 60
_MODEL_LOCK = threading.RLock()
_KIWI_LOCK = threading.RLock()


@lru_cache(maxsize=1)
def kiwi():
    from kiwipiepy import Kiwi

    return Kiwi(num_workers=1)


def lexical_tokens(text: str) -> list[str]:
    with _KIWI_LOCK:
        tokens = [
            token.form.casefold()
            for token in kiwi().tokenize(normalize_text(text))
            if token.tag.startswith(("NN", "VV", "VA", "XR"))
        ]
    # 영어 약어·숫자·하이픈 전문용어 보존. Kiwi SL/SN과 중복 집계하지 않는다.
    return tokens + re.findall(
        r"[a-z]+(?:[-/][a-z0-9]+)*|\d+(?:\.\d+)?", text.casefold()
    )


@lru_cache(maxsize=4)
def _load_model(model_name: str, device: str):
    import torch
    from sentence_transformers import SentenceTransformer

    # macOS CPU에서 과도한 스레드 생성으로 인한 충돌 방지.
    torch.set_num_threads(int(os.getenv("RAG_TORCH_THREADS", "1")))
    return SentenceTransformer(model_name, device=device)


def encode(
    texts: list[str], model_name: str = EMBEDDING_MODEL, *, progress=False, query=False
) -> np.ndarray:
    with _MODEL_LOCK:
        model = _load_model(model_name, os.getenv("RAG_DEVICE", "cpu"))
        if "multilingual-e5" in model_name:
            prefix = "query: " if query else "passage: "
            texts = [prefix + text for text in texts]
        return np.asarray(
            model.encode(
                texts,
                batch_size=int(os.getenv("RAG_BATCH_SIZE", "1")),
                normalize_embeddings=True,
                show_progress_bar=progress,
                convert_to_numpy=True,
            ),
            dtype="float32",
        )


def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    scores = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, 1):
            scores[idx] = scores.get(idx, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))


class HybridRetriever:
    def __init__(
        self,
        agent: str,
        index_dir: Path = INDEX_DIR,
        *,
        model=EMBEDDING_MODEL,
        data_dir: Path = DATA_DIR,
    ):
        import faiss
        from rank_bm25 import BM25Okapi

        stamp = fingerprint(agent, data_dir, model)
        directory = index_dir / GROUPS[agent] / stamp
        if not (directory / "manifest.json").exists():
            raise FileNotFoundError(
                "현재 PDF/설정의 색인이 없습니다. python -m src.rag.build_index 실행"
            )
        self.agent, self.model = agent, model
        self.chunks = json.loads((directory / "chunks.json").read_text())
        self.index = faiss.read_index(str(directory / "dense.faiss"))
        self.lexical = json.loads((directory / "tokens.json").read_text())
        if len(self.chunks) != self.index.ntotal or len(self.lexical) != len(
            self.chunks
        ):
            raise ValueError("색인 파일의 청크 수가 일치하지 않습니다.")
        self.bm25 = BM25Okapi(self.lexical)

    def search(
        self, query: str, *, top_k=TOP_K, topic=None, doc_ids=None, mode="hybrid"
    ):
        if not query.strip() or top_k < 1:
            raise ValueError("질문과 양수 top_k가 필요합니다.")
        if mode not in ("dense", "bm25", "hybrid"):
            raise ValueError("mode는 dense/bm25/hybrid입니다.")
        eligible = [
            i
            for i, chunk in enumerate(self.chunks)
            if chunk["agent"] == self.agent
            and (topic is None or topic in chunk["topics"])
            and (doc_ids is None or chunk["doc_id"] in doc_ids)
        ]
        if not eligible:
            return []
        rankings = []
        if mode in ("dense", "hybrid"):
            vector = encode([query], self.model, query=True)
            _, indices = self.index.search(vector, self.index.ntotal)
            allowed = set(eligible)
            rankings.append([int(i) for i in indices[0] if i in allowed][:top_k])
        if mode in ("bm25", "hybrid"):
            tokens = lexical_tokens(query)
            scores = (
                self.bm25.get_scores(tokens) if tokens else np.zeros(len(self.chunks))
            )
            query_set = set(tokens)
            matches = [i for i in eligible if query_set.intersection(self.lexical[i])]
            rankings.append(sorted(matches, key=lambda i: (-scores[i], i))[:top_k])
        return [
            {**self.chunks[i], "retrieval_score": score}
            for i, score in rrf(rankings)[:top_k]
        ]


def main():
    parser = argparse.ArgumentParser(description="RAG 검색 결과 확인 (API 키 불필요)")
    parser.add_argument("--agent", choices=GROUPS, required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--mode", choices=["dense", "bm25", "hybrid"], default="hybrid")
    parser.add_argument("--topic")
    args = parser.parse_args()
    results = HybridRetriever(args.agent).search(
        args.query, mode=args.mode, topic=args.topic
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
