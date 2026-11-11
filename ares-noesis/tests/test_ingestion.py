import pytest

from noesis.ingestion.claims import extract_claims, extract_stats, extract_triple, triples_contradict
from noesis.ingestion.parse import InvalidDocument, parse_document, validate_upload
from tests.conftest import DOC_TEXT, make_pdf


def test_pdf_parse_keeps_page_and_sections():
    d = parse_document("p.pdf", make_pdf())
    assert d.kind == "pdf" and d.n_pages == 1
    secs = {s.section for s in d.sentences}
    assert {"abstract", "results", "limitations"} <= secs
    assert "references" not in secs and d.dois == ["10.1000/xyz123"]


def test_claims_traceable_and_typed():
    d = parse_document("p.pdf", make_pdf())
    cl = extract_claims(d)
    f = [c for c in cl if c["kind"] == "finding"]
    assert any(c["meta"]["triple"] == {"subject": "graphene coating", "relation": "increases", "object": "battery lifespan", "negated": False, "method": "rule_v1"} for c in f)
    assert all(c["page"] == 1 and c["section"] for c in cl)
    assert any(c["kind"] == "limitation" for c in cl)
    assert any(c["kind"] == "equation_candidate" and c["meta"]["lhs"].startswith("(a+b)") for c in cl)
    causal = [c for c in f if "causes" in c["text"]]
    assert causal and causal[0]["meta"]["language"] == "causal"


def test_stats_extraction_variants():
    s = extract_stats("t(28) = 2.10, p = .045; F(1, 40) = 4.50, p < .05; r(28) = .45, p = .01; χ2(2) = 6.0, p = .05")
    assert [x["test"] for x in s] == ["t", "F", "chi2", "r"]


def test_triple_negation_and_contradiction():
    a = extract_triple("Dose increases yield.")
    b = extract_triple("Dose decreases yield.")
    n = extract_triple("Dose does not increase yield.")
    assert triples_contradict(a, b) and triples_contradict(a, n) and not triples_contradict(b, n)


@pytest.mark.parametrize("name,data,msg", [
    ("a.exe", b"x", "unsupported"), ("a.pdf", b"", "empty"), ("a.pdf", b"not a pdf", "PDF"),
    ("a.txt", b"\xff\xfe\x00bad", "UTF-8")])
def test_invalid_uploads(name, data, msg):
    with pytest.raises(InvalidDocument, match=msg):
        parse_document(name, data)


def test_corrupt_pdf_and_oversize():
    with pytest.raises(InvalidDocument):
        parse_document("a.pdf", b"%PDF-1.4 garbage")
    with pytest.raises(InvalidDocument, match="size"):
        validate_upload("a.txt", b"x" * 10, 5)
