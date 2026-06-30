"""Corpus parsing and chunking for the RAG ingestion pipeline (Epic C, story C0 — #30).

Frontmatter is a hand-rolled `key: value` reader, not YAML/PyYAML — the shape used by
`backend/rag/corpus/*.md` (three flat keys) is too trivial to justify the dependency.
Chunking is heading-bounded with no overlap: this is a small, hand-authored corpus
where sections are already semantically self-contained, so overlap would mostly
create near-duplicate chunks rather than improve retrieval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MAX_SECTION_WORDS = 220
TARGET_CHUNK_WORDS = 200  # upper end of the 150-220 word target band for split chunks

_HEADING_RE = re.compile(r"^## .+$", re.MULTILINE)


@dataclass(frozen=True)
class CorpusDoc:
    source: str
    title: str
    url: Optional[str]
    chunks: list[str]


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a `---\\nkey: value\\n...\\n---\\nbody` file into (fields, body)."""
    if not text.startswith("---"):
        raise ValueError("corpus file is missing frontmatter")
    _, _, rest = text.partition("---\n")
    raw_fm, sep, body = rest.partition("\n---")
    if not sep:
        raise ValueError("corpus file frontmatter is not closed with '---'")
    fields: dict[str, str] = {}
    for line in raw_fm.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body.lstrip("\n")


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


def _word_count(text: str) -> int:
    return len(text.split())


def _chunk_section(section_text: str) -> list[str]:
    """Split an oversized section into ~150-220 word, paragraph-bounded chunks."""
    if _word_count(section_text) <= MAX_SECTION_WORDS:
        return [section_text]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for para in _split_paragraphs(section_text):
        para_words = _word_count(para)
        if current and current_words + para_words > TARGET_CHUNK_WORDS:
            chunks.append("\n\n".join(current))
            current = []
            current_words = 0
        current.append(para)
        current_words += para_words
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _split_sections(body: str) -> list[str]:
    """Split a doc body on `##` headings; each section keeps its heading line."""
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return [body.strip()] if body.strip() else []
    sections = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append(body[start:end].strip())
    return sections


def parse_corpus_file(path: Path) -> CorpusDoc:
    """Parse one corpus markdown file into a CorpusDoc of heading-bounded chunks.

    Deterministic: chunking is purely structural (headings, then paragraphs), so
    the same file always produces the same chunk list.
    """
    text = path.read_text(encoding="utf-8")
    fields, body = _parse_frontmatter(text)
    source = fields.get("source", "").strip()
    title = fields.get("title", "").strip()
    url = fields.get("url", "").strip() or None
    if not source:
        raise ValueError(f"{path}: frontmatter is missing 'source'")
    if not title:
        raise ValueError(f"{path}: frontmatter is missing 'title'")

    chunks: list[str] = []
    for section in _split_sections(body):
        chunks.extend(_chunk_section(section))

    return CorpusDoc(source=source, title=title, url=url, chunks=chunks)
