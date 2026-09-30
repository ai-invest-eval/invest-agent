"""PDF → 모델 토큰 청킹 → FAISS + Kiwi BM25 색인. fingerprint로 기존 색인 재사용."""

import argparse
import json
import os
import tempfile
from pathlib import Path

from src.config import EMBEDDING_MODEL
from src.rag.documents import (
    CHUNK_OVERLAP_TOKENS,
    CHUNK_SIZE_TOKENS,
    DATA_DIR,
    GROUPS,
    chunk_pages,
    fingerprint,
    iter_pages,
)
from src.rag.retrieval import INDEX_DIR, encode, lexical_tokens

TECHNOLOGY_DIR = DATA_DIR / "technology"
MARKET_DIR = DATA_DIR / "market"


def build_indexes(*, agents=("tech", "market"), force=False, model=EMBEDDING_MODEL):
    import faiss
    from transformers import AutoTokenizer

    tokenizer = None
    for agent in agents:
        stamp = fingerprint(agent, model=model)
        parent = INDEX_DIR / GROUPS[agent]
        directory = parent / stamp
        if not force and all(
            (directory / f).exists()
            for f in ("manifest.json", "dense.faiss", "chunks.json", "tokens.json")
        ):
            print(f"{agent}: 기존 색인 재사용", flush=True)
            continue
        if tokenizer is None:
            tokenizer = AutoTokenizer.from_pretrained(EMBEDDING_MODEL, use_fast=True)
        pages = list(iter_pages(agent))
        chunks = chunk_pages(pages, tokenizer)
        if not chunks:
            raise ValueError(f"{agent}: 청크가 없습니다.")
        print(f"{agent}: 텍스트 페이지 {len(pages)}, {len(chunks)}개 청크", flush=True)
        vectors = encode([c["text"] for c in chunks], model, progress=True)
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        tokens = [lexical_tokens(c["text"]) for c in chunks]
        manifest = {
            "fingerprint": stamp,
            "model": model,
            "agent": agent,
            "chunk_count": len(chunks),
            "dimension": vectors.shape[1],
            "chunk_size": CHUNK_SIZE_TOKENS,
            "chunk_overlap": CHUNK_OVERLAP_TOKENS,
        }
        parent.mkdir(parents=True, exist_ok=True)
        # 독자는 manifest가 있는 완성 색인만 연다. 모델/PDF별 디렉터리로 비교 실험도 분리.
        with tempfile.TemporaryDirectory(dir=parent) as temporary:
            staging = Path(temporary)
            faiss.write_index(index, str(staging / "dense.faiss"))
            for filename, value in [
                ("chunks.json", chunks),
                ("tokens.json", tokens),
                ("manifest.json", manifest),
            ]:
                (staging / filename).write_text(
                    json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            directory.mkdir(exist_ok=True)
            for filename in (
                "dense.faiss",
                "chunks.json",
                "tokens.json",
                "manifest.json",
            ):
                os.replace(staging / filename, directory / filename)
        print(f"{agent}: 저장 완료 → {directory}", flush=True)


def main():
    from dotenv import load_dotenv

    from src.config import PROJECT_ROOT

    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=["tech", "market", "all"], default="all")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--model", default=EMBEDDING_MODEL)
    args = parser.parse_args()
    agents = ("tech", "market") if args.agent == "all" else (args.agent,)
    build_indexes(agents=agents, force=args.force, model=args.model)


if __name__ == "__main__":
    main()
