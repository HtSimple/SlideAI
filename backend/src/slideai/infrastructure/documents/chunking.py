import re
from dataclasses import dataclass

from slideai.infrastructure.documents.parsers import LocatedText

_TOKEN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:[._'-][A-Za-z0-9]+)*|[^\s]")


@dataclass(frozen=True)
class ChunkedText:
    content: str
    token_count: int
    page_number: int | None
    section_title: str | None
    paragraph_index: int | None


def chunk_located_text(
    located_text: list[LocatedText], *, chunk_size: int = 800, overlap: int = 120
) -> list[ChunkedText]:
    if chunk_size < 1 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be smaller than chunk_size")

    chunks: list[ChunkedText] = []
    for source in located_text:
        matches = list(_TOKEN.finditer(source.text))
        if not matches:
            continue
        start = 0
        while start < len(matches):
            end = min(start + chunk_size, len(matches))
            content = source.text[matches[start].start() : matches[end - 1].end()].strip()
            if content:
                chunks.append(
                    ChunkedText(
                        content=content,
                        token_count=end - start,
                        page_number=source.page_number,
                        section_title=source.section_title,
                        paragraph_index=source.paragraph_index,
                    )
                )
            if end == len(matches):
                break
            start = end - overlap
    return chunks
