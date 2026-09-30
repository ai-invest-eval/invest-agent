"""인용 문장이 원문에 있는지 확인하는 공통 규칙.

LLM은 원문을 조금씩 바꿔 인용한다(띄어쓰기·조사·기호·말줄임). 글자 그대로 일치하면
바로 인정하고, 아니면 공백·기호를 뺀 5글자 조각의 60% 이상이 원문에 있을 때 인정한다.
원문에 없는 문장은 대부분의 조각이 원문에 없어 여전히 걸러진다.
"""

import re
import unicodedata

NGRAM = 5
MIN_OVERLAP = 0.6
_PUNCT = re.compile(r"[\"'“”‘’「」『』…·.,!?()\[\]:;\-–—]")


def squash(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text or "")).casefold()


def quote_in(quote: str | None, source: str | None) -> bool:
    if not quote or not source or len(squash(quote)) < 4:
        return False
    if quote in source or squash(quote) in squash(source):
        return True
    q = squash(_PUNCT.sub("", quote))
    s = squash(_PUNCT.sub("", source))
    if len(q) < NGRAM * 2:
        return q in s
    grams = [q[i : i + NGRAM] for i in range(len(q) - NGRAM + 1)]
    return sum(g in s for g in grams) / len(grams) >= MIN_OVERLAP
