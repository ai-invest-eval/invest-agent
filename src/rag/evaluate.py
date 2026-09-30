"""수동 정답 원문을 이용한 Hit@1/3/5·MRR@5 측정. 검색 오류는 실패로 드러낸다."""

import argparse
import json
from pathlib import Path

from src.config import EMBEDDING_MODEL, PROJECT_ROOT
from src.rag.documents import normalize_text
from src.rag.retrieval import HybridRetriever


def is_relevant(hit, answers):
    return any(
        hit["doc_id"] == answer["doc_id"]
        and hit["page"] == answer["page"]
        and normalize_text(answer["quote"]) in normalize_text(hit["text"])
        for answer in answers
    )


def evaluate(rows, retrievers, mode):
    if not rows:
        raise ValueError("평가셋이 비어 있습니다.")
    ranks, details = [], []
    for row in rows:
        if not row.get("relevant"):
            raise ValueError("정답 출처·쪽수·원문 quote가 필요합니다.")
        retriever = retrievers[row["agent"]]
        if not any(is_relevant(hit, row["relevant"]) for hit in retriever.chunks):
            raise ValueError(
                f"정답이 색인에 없습니다: {row['id']}. 평가셋을 점검하세요."
            )
        results = retriever.search(row["question"], mode=mode, top_k=5)
        rank = next(
            (
                i
                for i, hit in enumerate(results, 1)
                if is_relevant(hit, row["relevant"])
            ),
            None,
        )
        ranks.append(rank)
        details.append(
            {
                "id": row["id"],
                "question": row["question"],
                "rank": rank,
                "retrieved_ids": [hit["id"] for hit in results],
            }
        )
    metrics = {
        f"Hit@{k}": sum(rank is not None and rank <= k for rank in ranks) / len(ranks)
        for k in [1, 3, 5]
    }
    return {
        "mode": mode,
        "count": len(rows),
        **metrics,
        "MRR@5": sum(1 / rank if rank else 0 for rank in ranks) / len(ranks),
        "details": details,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=PROJECT_ROOT / "samples/retrieval_eval.json"
    )
    parser.add_argument(
        "--mode", choices=["all", "dense", "bm25", "hybrid"], default="all"
    )
    parser.add_argument("--model", default=EMBEDDING_MODEL)
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "outputs/retrieval_metrics.json"
    )
    args = parser.parse_args()
    rows = json.loads(args.dataset.read_text(encoding="utf-8"))
    retrievers = {
        agent: HybridRetriever(agent, model=args.model)
        for agent in {row["agent"] for row in rows}
    }
    modes = ["dense", "bm25", "hybrid"] if args.mode == "all" else [args.mode]
    results = {
        "model": args.model,
        "dataset": str(args.dataset),
        "evaluation_note": "수동 작성한 소규모 개발셋. 모델 선정의 최종 검증이나 투자 기준 검증이 아님.",
        "results": [evaluate(rows, retrievers, mode) for mode in modes],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for result in results["results"]:
        print(
            json.dumps(
                {k: v for k, v in result.items() if k != "details"}, ensure_ascii=False
            )
        )
    print("저장:", args.output)


if __name__ == "__main__":
    main()
