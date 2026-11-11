"""Section-aware, sentence-aligned chunking for full text.

Chunks never cross a section boundary, so each chunk can be cited as (page, section, sentence range) and resolved back to the source.
Sentences are kept whole. Within a section, `overlap` sentences repeat at the start of the next chunk so an argument is not cut in half;
nothing is carried across a section boundary."""


def _make(cur: list) -> dict:
    return {"text": " ".join(s.text for _, s in cur), "page": cur[0][1].page, "section": cur[0][1].section,
            "first": cur[0][0], "last": cur[-1][0], "n_words": sum(len(s.text.split()) for _, s in cur)}


def chunk_sentences(sentences: list, target_words: int = 120, overlap: int = 1) -> list:
    """sentences: objects with .text, .page, .section. Returns [{text, page, section, first, last, n_words}]
    (first/last are sentence indexes into the input list)."""
    chunks, cur, fresh = [], [], 0          # fresh = sentences in cur that were not carried over as overlap
    for i, s in enumerate(sentences):
        if cur and cur[-1][1].section != s.section:
            if fresh:
                chunks.append(_make(cur))
            cur, fresh = [], 0
        w = len(s.text.split())
        if cur and fresh and sum(len(x.text.split()) for _, x in cur) + w > target_words:
            chunks.append(_make(cur))
            cur = cur[-overlap:] if overlap else []
            fresh = 0
        cur.append((i, s))
        fresh += 1
    if cur and fresh:
        chunks.append(_make(cur))
    return chunks
