"""Bounded local PDF ingestion. Page offsets refer to the stored extracted text."""

import base64
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

PDF_BYTES = 2_000_000
MAX_PAGES = 40
MAX_TEXT = 250_000
MAX_OCR_PAGES = 8
PARSER_SLOTS = threading.BoundedSemaphore(2)
TABLE_CAPTION = re.compile(r'^\s*Table\s+\d+[\w.:-]*\b', re.I)
TABLE_CELL = re.compile(r'\S(?:.*?\S)??(?=\s{2,}|$)')
MAX_TABLES = 20
MAX_TABLE_ROWS = 100


def _table_candidates(text, locations):
    """Identify simple captioned tables in layout-preserving PDF text."""
    tables = []
    bounded = False
    for location in locations:
        if location['method'] != 'text_layer':
            continue
        page = text[location['start']:location['end']]
        lines = []
        cursor = 0
        for line in page.splitlines(keepends=True):
            lines.append((cursor, line.rstrip('\r\n')))
            cursor += len(line)
        for index, (offset, line) in enumerate(lines):
            if not TABLE_CAPTION.match(line):
                continue
            rows = []
            columns = None
            anchors = None
            for row_offset, row_text in lines[index + 1:]:
                cells = list(TABLE_CELL.finditer(row_text))
                if not cells:
                    if rows:
                        break
                    continue
                if len(cells) < 2 or len(cells) > 12:
                    break
                positions = [cell.start() for cell in cells]
                if columns is None:
                    columns, anchors = len(cells), positions
                if len(cells) != columns or any(abs(a - b) > 4 for a, b in zip(anchors, positions)):
                    break
                rows.append([{'text': cell.group(),
                              'start': location['start'] + row_offset + cell.start(),
                              'end': location['start'] + row_offset + cell.end()}
                             for cell in cells])
                if len(rows) >= MAX_TABLE_ROWS:
                    bounded = True
                    break
            if len(rows) < 3 or not any(re.search(r'\d', cell['text']) for row in rows[1:] for cell in row):
                continue
            tables.append({'page': location['page'], 'caption': line.strip(),
                           'caption_start': location['start'] + offset,
                           'rows': rows, 'method': 'aligned_text_candidate',
                           'requires_review': True})
            if len(tables) >= MAX_TABLES:
                return tables, True
    return tables, bounded


class DocumentError(ValueError):
    pass


class DocumentUnavailable(RuntimeError):
    pass


def _command(directory, deadline, program, *args):
    executable = shutil.which(program)
    limit = shutil.which('prlimit')
    if not executable or not limit:
        raise DocumentUnavailable(f'PDF processing requires {program} and prlimit.')
    timeout = deadline - time.monotonic()
    if timeout <= 0:
        raise DocumentError('PDF processing exceeded its time limit.')
    try:
        result = subprocess.run(
            [limit, '--as=805306368', '--cpu=25', '--fsize=12000000', '--nofile=64',
             '--core=0', '--', executable, *args],
            env={'PATH': os.defpath, 'HOME': str(directory), 'TMPDIR': str(directory),
                 'LC_ALL': 'C', 'OMP_THREAD_LIMIT': '1'},
            cwd=directory, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DocumentError('PDF processing exceeded its time limit.') from exc
    except OSError as exc:
        raise DocumentUnavailable('PDF processing tools could not start.') from exc
    if result.returncode:
        raise DocumentError('The PDF could not be processed within the supported format and resource limits.')
    return result.stdout


def parse_pdf(raw, license_status, title='', study_id=''):
    if not raw.startswith(b'%PDF-') or len(raw) > PDF_BYTES:
        raise DocumentError('Choose a PDF no larger than 2 MB.')
    if not PARSER_SLOTS.acquire(blocking=False):
        raise DocumentUnavailable('PDF processing is busy. Try again shortly.')
    try:
        return _parse(raw, license_status, title, study_id)
    finally:
        PARSER_SLOTS.release()


def _parse(raw, license_status, title, study_id):
    deadline = time.monotonic() + 45
    digest = hashlib.sha256(raw).hexdigest()
    with tempfile.TemporaryDirectory(prefix='ares-pdf-') as work:
        directory = Path(work)
        (directory / 'source.pdf').write_bytes(raw)
        info = _command(directory, deadline, 'pdfinfo', 'source.pdf')
        pages = re.search(rb'^Pages:\s+(\d+)\s*$', info, re.MULTILINE)
        if not pages or not 1 <= int(pages[1]) <= MAX_PAGES:
            raise DocumentError('The PDF must contain between 1 and 40 pages.')
        if not re.search(rb'^Encrypted:\s+no\b', info, re.MULTILINE):
            raise DocumentError('Encrypted PDFs are unsupported.')
        page_count = int(pages[1])
        _command(directory, deadline, 'pdftotext', '-layout', '-enc', 'UTF-8', 'source.pdf', 'pages.txt')
        extracted = (directory / 'pages.txt').read_text(encoding='utf-8', errors='replace').split('\f')
        if len(extracted) < page_count:
            raise DocumentError('The PDF did not produce a reliable page map.')
        chunks, locations, blank_pages = [], [], []
        start = ocr_pages = 0
        for page, value in enumerate(extracted[:page_count], start=1):
            method = 'text_layer'
            value = value.strip()
            if not value:
                ocr_pages += 1
                if ocr_pages > MAX_OCR_PAGES:
                    raise DocumentError('Split scanned PDFs into files with at most 8 pages that need OCR.')
                _command(directory, deadline, 'pdftoppm', '-f', str(page), '-l', str(page),
                         '-scale-to', '1800', '-singlefile', '-gray', '-png', 'source.pdf', 'page')
                value = _command(directory, deadline, 'tesseract', 'page.png', 'stdout', '-l', 'eng').decode(
                    'utf-8', errors='replace').strip()
                method = 'ocr'
            if not value:
                blank_pages.append(page)
                continue
            value = value.replace('\x00', '\ufffd')
            end = start + len(value)
            if end > MAX_TEXT:
                raise DocumentError('Extracted PDF text exceeds 250,000 characters. Split the document.')
            chunks.append(value)
            locations.append({'page': page, 'start': start, 'end': end, 'method': method})
            start = end + 2
        if not chunks:
            raise DocumentError('No readable text was found. Scanned pages use English OCR.')
    text = '\n\n'.join(chunks)
    tables, tables_bounded = _table_candidates(text, locations)
    return {
        'title': title or f'PDF document {digest[:12]}',
        'url': f'urn:sha256:{digest}',
        'text': text,
        'license_status': license_status,
        'study_id': study_id,
        'origin': 'user_pdf',
        'document': {
            'original_format': 'pdf', 'original_sha256': digest,
            'original_content_base64': base64.b64encode(raw).decode('ascii'),
            'page_count': page_count, 'locations': locations, 'blank_pages': blank_pages,
            'tables': tables, 'tables_bounded': tables_bounded,
            'table_extraction': {
                'scope': 'Captioned tables with consistently aligned text-layer rows.',
                'ocr_pages_skipped': ocr_pages,
                'limitations': 'Candidates require page review; merged cells and scanned tables are unsupported.',
            },
        },
    }
