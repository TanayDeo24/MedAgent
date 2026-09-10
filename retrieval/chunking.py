"""Chunking for PubMed abstracts.

Chunking strategy: fixed word-count windows with overlap, rather than
paragraph-level. PubMed abstracts are returned as a single joined block of
text by PubMedTool (structured "Label: text" sections get concatenated with
spaces, see PubMedTool._parse_xml_article) -- there is no reliable paragraph
structure to split on. A fixed window also keeps each chunk within the
embedding model's sequence limit: all-MiniLM-L6-v2 truncates at 256 word-piece
tokens, and at ~1.3 tokens/word a 180-word chunk lands comfortably under that
(~235 tokens) while a handful of longer structured abstracts (background/
methods/results/conclusion) still get split into 2-3 retrievable chunks
instead of being silently truncated.

Each chunk is embedded as "Title: {title}\n\n{chunk text}" so the title's
strong topical signal carries into every chunk of a multi-chunk abstract,
not just the first.
"""

from typing import Any, Dict, List

CHUNK_SIZE_WORDS = 180
CHUNK_OVERLAP_WORDS = 30


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_WORDS, overlap: int = CHUNK_OVERLAP_WORDS) -> List[str]:
    """Split text into overlapping fixed-size word windows."""
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    step = chunk_size - overlap
    for start in range(0, len(words), step):
        window = words[start:start + chunk_size]
        if not window:
            break
        chunks.append(" ".join(window))
        if start + chunk_size >= len(words):
            break
    return chunks


def chunk_abstract(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Chunk one corpus record (abstract + metadata) into retrievable chunks.

    Returns a list of chunk dicts carrying enough metadata for citation:
    pmid, title, year, journal, url, chunk_index, embed_text (what gets
    embedded), chunk_text (the raw abstract text for this window, no title
    prefix -- what gets shown/cited back to the user).
    """
    abstract = record["abstract"]
    title = record.get("title", "")
    raw_chunks = chunk_text(abstract)

    out = []
    for idx, chunk in enumerate(raw_chunks):
        out.append({
            "pmid": record["pmid"],
            "title": title,
            "journal": record.get("journal", ""),
            "year": record.get("year", ""),
            "pub_date": record.get("pub_date", ""),
            "doi": record.get("doi", ""),
            "url": record.get("url", ""),
            "chunk_index": idx,
            "num_chunks": len(raw_chunks),
            "chunk_text": chunk,
            "embed_text": f"Title: {title}\n\n{chunk}",
        })
    return out
