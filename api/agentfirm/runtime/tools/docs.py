"""Document text extraction (Document Processing engine, minimal Phase-4a scope)."""

from __future__ import annotations

import io


def pdf_text(data: bytes, max_pages: int = 200) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for i, page in enumerate(reader.pages[:max_pages], 1):
        pages.append(f"[page {i}] {page.extract_text() or ''}")
    return "\n".join(pages)


def chunk_text(text: str, *, size: int = 1200, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind(". ", start + size // 2, end)
            end = cut + 1 if cut > 0 else end
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks
