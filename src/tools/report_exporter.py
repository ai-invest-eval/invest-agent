"""보고서 Markdown → HTML → PDF 변환 (WeasyPrint).

흑백 기본 서식, A4, 한글 폰트는 설치된 것 중 앞에서부터 사용한다.
"""

from pathlib import Path

import markdown

# 폰트는 OS별로 설치된 것을 차례로 찾는다 (Windows / macOS / Linux).
FONT_STACK = (
    '"Malgun Gothic", "맑은 고딕", "Apple SD Gothic Neo", "AppleGothic", '
    '"Noto Sans CJK KR", "Noto Sans KR", "NanumGothic", sans-serif'
)

# 쪽수가 넘칠 때 한 단계씩 줄이는 본문/표 글자 크기(pt)
FONT_LEVELS = [(10, 8.8), (9.5, 8.4), (9, 8), (8.5, 7.6)]


def _css(level: int) -> str:
    body, table = FONT_LEVELS[min(level, len(FONT_LEVELS) - 1)]
    return f"""
@page {{
  size: A4;
  margin: 15mm 16mm 15mm 16mm;
  @bottom-center {{ content: counter(page) " / " counter(pages); font-size: 8pt; }}
}}
body {{ font-family: {FONT_STACK}; font-size: {body}pt; line-height: 1.5; color: #000; }}
h1 {{ font-size: {body + 6}pt; margin: 0 0 2pt 0; }}
h2 {{ font-size: {body + 3}pt; margin: 12pt 0 4pt 0; border-bottom: 1px solid #000; padding-bottom: 2pt; }}
h3 {{ font-size: {body + 1}pt; margin: 8pt 0 3pt 0; }}
p, li {{ margin: 2pt 0; }}
ul, ol {{ margin: 2pt 0; padding-left: 16pt; }}
table {{ border-collapse: collapse; width: 100%; font-size: {table}pt; margin: 4pt 0; }}
th, td {{ border: 1px solid #000; padding: 2pt 4pt; vertical-align: top; }}
th {{ font-weight: bold; text-align: center; }}
td.num {{ text-align: right; }}
.meta {{ font-size: {table}pt; margin-bottom: 6pt; }}
.note {{ font-size: {table}pt; }}
h2.summary + * {{ margin-top: 4pt; }}
.page-break {{ page-break-before: always; }}
"""


def markdown_to_html(md_text: str, level: int = 0) -> str:
    body = markdown.markdown(md_text, extensions=["tables", "sane_lists", "attr_list"])
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f"<style>{_css(level)}</style></head><body>{body}</body></html>"
    )


def render_pdf(md_text: str, level: int = 0) -> tuple[bytes, int]:
    """PDF 바이트와 쪽수. WeasyPrint는 호출 시점에만 import한다."""
    from weasyprint import HTML

    document = HTML(string=markdown_to_html(md_text, level)).render()
    return document.write_pdf(), len(document.pages)


def save_outputs(md_text: str, pdf_bytes: bytes, out_dir: Path, stem: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{stem}.md"
    pdf_path = out_dir / f"{stem}.pdf"
    md_path.write_text(md_text, encoding="utf-8")
    pdf_path.write_bytes(pdf_bytes)
    return {"markdown": str(md_path), "pdf": str(pdf_path)}
