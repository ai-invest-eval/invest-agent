"""PDF 페이지·원문 쪽수·서지정보를 보존하는 토큰 청킹."""

import hashlib
import json
import re
import unicodedata
from pathlib import Path

from src.config import EMBEDDING_MODEL, PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
GROUPS = {"tech": "technology", "market": "market"}
CHUNK_SIZE_TOKENS = 1000
CHUNK_OVERLAP_TOKENS = 200
TOP_K = 5
INDEX_VERSION = 1


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def load_metadata(data_dir: Path = DATA_DIR) -> dict:
    data = json.loads((data_dir / "doc_metadata.json").read_text(encoding="utf-8"))
    return {unicodedata.normalize("NFC", key): value for key, value in data.items()}


def pdf_paths(agent: str, data_dir: Path = DATA_DIR) -> list[Path]:
    if agent not in GROUPS:
        raise ValueError("agent는 tech 또는 market이어야 합니다.")
    paths = sorted((data_dir / GROUPS[agent]).glob("*.pdf"))
    if not paths:
        raise FileNotFoundError(f"PDF가 없습니다: {data_dir / GROUPS[agent]}")
    return paths


def fingerprint(
    agent: str, data_dir: Path = DATA_DIR, model: str = EMBEDDING_MODEL
) -> str:
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            [INDEX_VERSION, model, CHUNK_SIZE_TOKENS, CHUNK_OVERLAP_TOKENS]
        ).encode()
    )
    digest.update((data_dir / "doc_metadata.json").read_bytes())
    for path in pdf_paths(agent, data_dir):
        digest.update(unicodedata.normalize("NFC", path.name).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def iter_pages(agent: str, data_dir: Path = DATA_DIR):
    from pypdf import PdfReader

    metadata = load_metadata(data_dir)
    for path in pdf_paths(agent, data_dir):
        name = unicodedata.normalize("NFC", path.name)
        if name not in metadata:
            raise ValueError(f"서지정보가 없습니다: {name}")
        meta = metadata[name]
        if meta["folder"] != GROUPS[agent]:
            raise ValueError(f"문서 폴더와 메타데이터 불일치: {name}")
        reader = PdfReader(path)
        original_pages = meta.get("page_offset")
        if original_pages is not None and len(original_pages) != len(reader.pages):
            raise ValueError(f"발췌 쪽수 매핑 불일치: {name}")
        text_pages = 0
        for i, page in enumerate(reader.pages):
            text = normalize_text(page.extract_text() or "")
            if text:
                text_pages += 1
                yield {
                    "doc_id": meta["doc_id"],
                    "file": name,
                    "agent": agent,
                    "topics": meta["topics"],
                    "local_page": i + 1,
                    "page": original_pages[i] if original_pages else i + 1,
                    "text": text,
                    "metadata": meta,
                }
        if not text_pages:
            raise ValueError(f"텍스트가 없는 PDF입니다. OCR이 필요합니다: {name}")


def chunk_pages(pages, tokenizer, size=CHUNK_SIZE_TOKENS, overlap=CHUNK_OVERLAP_TOKENS):
    if not 0 <= overlap < size:
        raise ValueError("겹침은 0 이상, 청크 크기 미만이어야 합니다.")
    chunks = []
    for page in pages:
        encoded = tokenizer(
            page["text"],
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        offsets = encoded["offset_mapping"]
        for start in range(0, len(offsets), size - overlap):
            end = min(start + size, len(offsets))
            text = page["text"][offsets[start][0] : offsets[end - 1][1]].strip()
            if text:
                chunks.append(
                    {
                        **page,
                        "text": text,
                        "token_count": end - start,
                        "id": f"{page['doc_id']}:p{page['page']}:t{start}",
                    }
                )
            if end == len(offsets):
                break
    return chunks


def reference_for(chunk: dict, company: str) -> dict:
    allowed = {
        "title",
        "issuer",
        "year",
        "doc_type",
        "url",
        "authors",
        "published_date",
        "site_name",
        "journal",
        "volume",
        "issue",
        "pages",
    }
    return {
        **{key: value for key, value in chunk["metadata"].items() if key in allowed},
        "company": company,
        "agent": chunk["agent"],
        "source": "RAG",
        "page": chunk["page"],
    }
