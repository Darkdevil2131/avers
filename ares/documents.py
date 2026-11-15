import hashlib
import base64
import re
from defusedxml import ElementTree as ET

ALLOWED_LICENSE = re.compile(r'https?://creativecommons.org/(?:licenses/(?:by|by-sa)/[134]\.0|publicdomain/zero/1\.0)/?$', re.I)
# A subset of Europe PMC documents declares this external JATS DTD. Remove
# only its declaration; the parser still forbids all DTDs and entity declarations.
JATS_EXTERNAL_DOCTYPE = re.compile(
    rb'\A((?:\xef\xbb\xbf)?\s*(?:<\?xml\s+[^?]*\?>\s*)?)'
    rb'<!DOCTYPE\s+article\s+PUBLIC\s+"-//NLM//DTD JATS [^"<>\[\]]{1,250}"\s+'
    rb'"JATS-[A-Za-z0-9._-]+\.dtd"\s*>\s*',
)


class UnsupportedLicense(ValueError):
    pass


class DocumentLimitError(ValueError):
    pass


def _text(node):
    return ' '.join(''.join(node.itertext()).split()) if node is not None else ''


def _jats_tables(parts):
    """Preserve physical rows and span attributes for explicit JATS HTML-style tables."""
    tables = []
    cells_left = 2000
    for part in parts:
        for wrapper in part.iter('table-wrap'):
            table = wrapper.find('table')
            if table is None:
                continue
            rows = []
            for row in table.findall('tr') + [
                row for group in table if group.tag in {'thead', 'tbody', 'tfoot'}
                for row in group.findall('tr')
            ]:
                if cells_left <= 0:
                    break
                cells = []
                for cell in row:
                    if cell.tag not in {'td', 'th'}:
                        continue
                    if cells_left <= 0:
                        break
                    value = _text(cell)
                    cells.append({
                        'text': value[:2000], 'text_truncated': len(value) > 2000,
                        'header': cell.tag == 'th',
                        'rowspan': cell.get('rowspan', '1')[:20],
                        'colspan': cell.get('colspan', '1')[:20],
                    })
                    cells_left -= 1
                if cells:
                    rows.append(cells)
            if rows:
                tables.append({
                    'id': wrapper.get('id'), 'label': _text(wrapper.find('label'))[:200],
                    'caption': _text(wrapper.find('caption'))[:2000], 'rows': rows,
                })
            if len(tables) >= 20 or cells_left <= 0:
                return tables, True
    return tables, False


def parse_jats(raw: bytes, pmcid: str):
    if len(raw)>4_000_000:
        raise DocumentLimitError('XML exceeds 4 MB budget')
    parse_input = JATS_EXTERNAL_DOCTYPE.sub(rb'\1', raw, count=1)
    root=ET.fromstring(parse_input, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    text = _text
    licenses=root.findall('.//permissions/license')
    links=[v for node in licenses for descendant in node.iter() for k,v in descendant.attrib.items() if k.endswith('href')]
    license_url=next((x for x in links if ALLOWED_LICENSE.fullmatch(x)),None)
    if license_url is None:
        raise UnsupportedLicense('Full-text license is not an explicitly supported CC BY, CC BY-SA or CC0 license')
    title=text(root.find('.//article-title'))
    chunks=[];locations=[];offset=0
    # Preserve normalized section text with location paths; original XML hash accompanies it.
    parts = root.findall('.//abstract') + root.findall('./body')
    for part in parts:
        for node in part.iter():
            if node.tag not in {'p','table-wrap'}:continue
            value=text(node)
            if not value:continue
            if offset+len(value)>250000:raise DocumentLimitError('Article exceeds 250000-character ingestion limit')
            chunks.append(value);locations.append({'id':node.get('id'),'kind':node.tag,'start':offset,'end':offset+len(value)})
            offset+=len(value)+2
    if not chunks:raise ValueError('No article body or abstract text')
    doi=next((text(n) for n in root.findall('.//article-id') if n.get('pub-id-type')=='doi'),None)
    refs=[]
    for node in root.findall('.//ref//pub-id'):
        if node.get('pub-id-type')=='pmcid' and re.fullmatch(r'PMC\d+',text(node)):refs.append(text(node))
    tables, tables_bounded = _jats_tables(parts)
    return {'title':title,'text':'\n\n'.join(chunks),'url':f'https://europepmc.org/articles/{pmcid}',
            'study_id':doi or pmcid,'license_status':license_url,'origin':'europepmc_fulltext',
            'document':{'original_sha256':hashlib.sha256(raw).hexdigest(),'original_xml_base64':base64.b64encode(raw).decode('ascii'),'locations':locations,'references':list(dict.fromkeys(refs))[:20], 'license':license_url,
                        'tables': tables, 'tables_bounded': tables_bounded}}

def parse_bioc(raw: bytes, pmcid: str):
    import json
    if len(raw)>4_000_000:raise DocumentLimitError('BioC exceeds 4 MB budget')
    collections=json.loads(raw)
    if not isinstance(collections,list):raise ValueError('Unexpected BioC collection')
    documents=[d for collection in collections for d in collection.get('documents',[]) if d.get('id')==pmcid]
    if len(documents)!=1:raise ValueError('BioC document identity mismatch')
    document=documents[0]
    license_name=document.get('infons',{}).get('license','').strip().upper()
    if license_name not in {'CC BY','CC BY-SA','CC0'}:raise UnsupportedLicense('Unsupported BioC reuse license')
    chunks=[];locations=[];offset=0;title=pmcid;doi=None
    for passage in document.get('passages',[]):
        info=passage.get('infons',{});value=passage.get('text','').strip()
        if not isinstance(value,str):raise ValueError('Invalid BioC text')
        if info.get('type')=='front':title=value or title
        doi=doi or info.get('article-id_doi')
        if not value or str(info.get('section_type','')).upper() in {'REF','REFERENCES'}:continue
        if offset+len(value)>250000:raise DocumentLimitError('Article text budget exceeded')
        chunks.append(value);locations.append({'kind':info.get('type','passage'),'section':info.get('section_type'),'source_offset':passage.get('offset'),'start':offset,'end':offset+len(value)})
        offset+=len(value)+2
    if not chunks:raise ValueError('No BioC text passages')
    return {'title':title[:500],'text':'\n\n'.join(chunks),'url':f'https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/',
            'study_id':doi or pmcid,'license_status':license_name+' (NCBI BioC license metadata)','origin':'ncbi_bioc_fulltext',
            'document':{'original_sha256':hashlib.sha256(raw).hexdigest(),'original_format':'bioc_json','original_content_base64':base64.b64encode(raw).decode('ascii'),'license':license_name,'locations':locations,'references':[]}}
