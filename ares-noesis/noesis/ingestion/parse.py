"""Document validation + text/layout extraction. Keeps page + section for every sentence."""
import hashlib
import re
from dataclasses import dataclass, field


class InvalidDocument(ValueError):
    pass


ALLOWED_EXT = {".pdf", ".txt"}
SECTION_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+)?(abstract|introduction|background|related work|methods?|"
    r"materials and methods|methodology|experimental(?: setup)?|results(?: and discussion)?|"
    r"discussion|limitations|conclusions?|references|bibliography)\s*:?$",
    re.I,
)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>\]\)]+", re.I)
_ABBR = ["et al.", "Fig.", "Figs.", "Eq.", "Eqs.", "e.g.", "i.e.", "vs.", "cf.", "Ref.", "No.", "approx."]


@dataclass
class Line:
    page: int
    section: str
    text: str


@dataclass
class Sentence:
    page: int
    section: str
    text: str


@dataclass
class ParsedDocument:
    kind: str
    n_pages: int
    title: str
    lines: list = field(default_factory=list)
    sentences: list = field(default_factory=list)
    references_text: str = ""
    dois: list = field(default_factory=list)
    tables: list = field(default_factory=list)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_upload(filename: str, data: bytes, max_bytes: int) -> str:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise InvalidDocument(f"unsupported file type '{ext}' (supported: .pdf, .txt)")
    if not data:
        raise InvalidDocument("empty file")
    if len(data) > max_bytes:
        raise InvalidDocument("file exceeds size limit")
    if ext == ".pdf" and data[:1024].find(b"%PDF-") < 0:
        raise InvalidDocument("file does not look like a PDF (missing %PDF- header)")
    return ext


def split_sentences(text: str) -> list:
    t = text
    for i, a in enumerate(_ABBR):
        t = t.replace(a, a.replace(".", f"<d{i}>"))
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\(\[])", t)
    out = []
    for p in parts:
        for i, a in enumerate(_ABBR):
            p = p.replace(a.replace(".", f"<d{i}>"), a)
        p = p.strip()
        if len(p) > 3:
            out.append(p)
    return out


def _norm_section(name: str) -> str:
    n = name.lower().strip(" :")
    n = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", n)
    if n.startswith("materials") or n.startswith("method") or n.startswith("experimental"):
        return "methods"
    if n.startswith("results"):
        return "results"
    if n.startswith("conclusion"):
        return "conclusion"
    if n.startswith("bibliography"):
        return "references"
    return n


def _join(buf: list) -> str:
    text = ""
    for l in buf:
        if text.endswith("-") and l[:1].islower():
            text = text[:-1] + l
        else:
            text = (text + " " + l).strip()
    return text


def _build(pages: list, kind: str, title_hint: str = "") -> ParsedDocument:
    lines, sentences, refs = [], [], []
    section = "front matter"
    for pno, text in pages:
        buf = []

        def flush():
            nonlocal buf
            if buf:
                joined = _join(buf)
                if section != "references":
                    for s in split_sentences(joined):
                        sentences.append(Sentence(pno, section, s))
            buf = []

        for raw in text.splitlines():
            s = raw.strip()
            if not s:
                continue
            if len(s) < 60 and SECTION_RE.match(s):
                flush()
                section = _norm_section(s)
                continue
            lines.append(Line(pno, section, s))
            if section == "references":
                refs.append(s)
            else:
                buf.append(s)
        flush()
    title = title_hint.strip()
    if not title and lines:
        for l in lines:
            if len(l.text) > 8:
                title = l.text
                break
    refs_text = "\n".join(refs)
    dois = sorted({d.rstrip(".,;") for d in DOI_RE.findall(refs_text)})
    return ParsedDocument(kind, len(pages), title, lines, sentences, refs_text, dois)


def _table_rows(pg, tb) -> list:
    """Rebuild cell text from word positions inside each cell box (find_tables().extract() can scramble glyph order, e.g. '519\\n.')."""
    import pymupdf
    rows = []
    for row in tb.rows:
        out = []
        for cell in row.cells:
            if cell is None:
                out.append("")
                continue
            words = pg.get_text("words", clip=pymupdf.Rect(cell))
            words.sort(key=lambda w: (round(w[1]), w[0]))
            out.append(" ".join(w[4] for w in words).strip())
        rows.append(out)
    return rows


def parse_document(filename: str, data: bytes, max_bytes: int = 50 * 1024 * 1024, max_pages: int = 400) -> ParsedDocument:
    ext = validate_upload(filename, data, max_bytes)
    if ext == ".txt":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise InvalidDocument(f"text file is not valid UTF-8: {e}")
        doc = _build([(1, text)], "txt")
    else:
        import pymupdf
        try:
            pdf = pymupdf.open(stream=data, filetype="pdf")
        except Exception as e:
            raise InvalidDocument(f"cannot open PDF: {e}")
        if pdf.needs_pass:
            raise InvalidDocument("PDF is encrypted")
        if len(pdf) > max_pages:
            raise InvalidDocument(f"PDF has {len(pdf)} pages (limit {max_pages})")
        pages = [(i + 1, p.get_text("text")) for i, p in enumerate(pdf)]
        if sum(len(t.strip()) for _, t in pages) < 50:
            raise InvalidDocument("no extractable text (scanned PDF? OCR is not enabled)")
        doc = _build(pages, "pdf", (pdf.metadata or {}).get("title", ""))
        for i, pg in enumerate(pdf):
            try:
                for tb in pg.find_tables().tables:
                    rows = _table_rows(pg, tb)
                    if len(rows) >= 2 and any(any(c for c in r) for r in rows):
                        doc.tables.append({"page": i + 1, "rows": rows[:60]})
            except Exception:
                pass  # table detection is best-effort; text extraction already succeeded
    if not doc.sentences:
        raise InvalidDocument("no body text found")
    return doc
