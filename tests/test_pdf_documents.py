from hashlib import sha256
from io import BytesIO
from pathlib import Path
import shutil

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
import pytest
from reportlab.pdfgen import canvas

from ares.pdf_export import FONT_PATH
from test_research import KEYS, client, project

pytestmark = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ('pdfinfo', 'pdftotext', 'pdftoppm', 'tesseract', 'prlimit'))
    or not Path(FONT_PATH).is_file(),
    reason='PDF tools and font are installed in the container and test job',
)


def fixture_pdf():
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(600, 800))
    pdf.drawString(42, 740, 'Humidity increased coating adhesion during the controlled test.')
    pdf.showPage()
    scan = Image.new('RGB', (1200, 1600), 'white')
    draw = ImageDraw.Draw(scan)
    font = ImageFont.truetype(FONT_PATH, 35)
    draw.text((75, 180), 'Humidity decreased coating adhesion.', font=font, fill='black')
    pdf.drawInlineImage(scan, 0, 0, width=600, height=800)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def table_pdf():
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(600, 800))
    pdf.drawString(40, 750, 'Table 1. Coating measurements')
    for y, row in [(720, ('Sample', 'Humidity', 'Adhesion')),
                   (700, ('A', '40%', '12 MPa')),
                   (680, ('B', '80%', '8 MPa'))]:
        for x, cell in zip((40, 200, 370), row):
            pdf.drawString(x, y, cell)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def test_pdf_structured_table_preserves_exact_page_spans(tmp_path):
    api = client(tmp_path)
    pid = project(api)
    route = f'/projects/{pid}/sources/pdf'
    response = api.post(route, params={'license_status': 'Synthetic test fixture'},
                        content=table_pdf(), headers={'Content-Type': 'application/pdf'})
    assert response.status_code == 201, response.text
    source_id = response.json()['id']
    sources = api.get(f'/projects/{pid}/sources').json()
    text = next(source['text'] for source in sources if source['id'] == source_id)
    document_route = f'/projects/{pid}/sources/{source_id}/document'
    document = api.get(document_route).json()
    table, = document['tables']
    assert table['page'] == 1 and table['requires_review']
    assert [[cell['text'] for cell in row] for row in table['rows']] == [
        ['Sample', 'Humidity', 'Adhesion'], ['A', '40%', '12 MPa'], ['B', '80%', '8 MPa']]
    for row in table['rows']:
        for cell in row:
            assert text[cell['start']:cell['end']] == cell['text']
    outsider = TestClient(api.app, headers={'Authorization': 'Bearer ' + KEYS['bob']})
    assert outsider.get(document_route).status_code == 404


def test_unsupported_layout_and_scanned_page_do_not_claim_table_structure():
    from ares.pdf_documents import _table_candidates

    text = ('Table 2. Synthetic observations\n'
            'Name  Result\nA  1\nThis wrapped row has no clear columns\nB  2\n')
    page = {'page': 1, 'start': 0, 'end': len(text), 'method': 'text_layer'}
    assert _table_candidates(text, [page])[0] == []
    assert _table_candidates(text, [{**page, 'method': 'ocr'}])[0] == []


def test_pdf_upload_ocr_provenance_and_download(tmp_path):
    api = client(tmp_path)
    pid = project(api)
    prefix = f'/projects/{pid}'
    raw = fixture_pdf()
    route = prefix + '/sources/pdf'
    headers = {'Content-Type': 'application/pdf'}
    params = {'title': 'Coating fixture', 'license_status': 'Synthetic test fixture', 'study_id': 'coating-fixture'}
    assert api.post(route, params=params, content=b'bad input', headers=headers).status_code == 422
    assert api.post(route, params=params, content=b'x' * 2_000_001, headers=headers).status_code == 413
    other = TestClient(api.app, headers={'Authorization': 'Bearer ' + KEYS['bob']})
    assert other.post(route, params=params, content=raw, headers=headers).status_code == 404
    upload = api.post(route, params=params, content=raw, headers=headers)
    assert upload.status_code == 201, upload.text
    source_id = upload.json()['id']
    assert upload.json()['page_count'] == 2
    source_root = prefix + f'/sources/{source_id}'
    document = api.get(source_root + '/document').json()
    assert document['original_sha256'] == sha256(raw).hexdigest()
    assert [(page['page'], page['method']) for page in document['locations']] == [
        (1, 'text_layer'), (2, 'ocr'),
    ]
    original = api.get(source_root + '/original.pdf')
    assert original.content == raw
    assert 'attachment' in original.headers['content-disposition']
    assert other.get(source_root + '/original.pdf').status_code == 404

    created = api.post(prefix + '/runs', json={'question': 'How does humidity affect coating adhesion?'})
    assert created.status_code == 201, created.text
    report_route = prefix + '/runs/' + created.json()['id'] + '/report'
    report = api.get(report_route).json()
    assert report['citations']
    assert all(citation['study_id'] == 'coating-fixture' for citation in report['citations'])
    pages = {page['page'] for citation in report['citations'] for page in citation['pdf_pages']}
    assert pages == {1, 2}
    assert 'PDF pages:' in api.get(report_route + '.md').text
    exported = api.get(report_route + '.pdf')
    assert exported.status_code == 200
    assert exported.headers['content-type'] == 'application/pdf'
    assert exported.content.startswith(b'%PDF-')
    assert other.get(report_route + '.pdf').status_code == 404
