import hashlib
import base64
import re
from defusedxml import ElementTree as ET

ALLOWED_LICENSE = re.compile(r'https?://creativecommons.org/(?:licenses/(?:by|by-sa)/[134]\.0|publicdomain/zero/1\.0)/?$', re.I)

def parse_jats(raw: bytes, pmcid: str):
    if len(raw)>4_000_000:
        raise ValueError('XML exceeds 4 MB budget')
    root=ET.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    def text(node):
        return ' '.join(''.join(node.itertext()).split()) if node is not None else ''
    licenses=root.findall('.//permissions/license')
    links=[v for node in licenses for descendant in node.iter() for k,v in descendant.attrib.items() if k.endswith('href')]
    license_url=next((x for x in links if ALLOWED_LICENSE.fullmatch(x)),None)
    if license_url is None:
        raise ValueError('Full-text license is not an explicitly supported CC BY, CC BY-SA or CC0 license')
    title=text(root.find('.//article-title'))
    chunks=[];locations=[];offset=0
    # Preserve normalized section text with location paths; original XML hash accompanies it.
    for part in root.findall('.//abstract')+root.findall('./body'):
        for node in part.iter():
            if node.tag not in {'p','table-wrap'}:continue
            value=text(node)
            if not value:continue
            if offset+len(value)>250000:raise ValueError('Article exceeds 250000-character ingestion limit')
            chunks.append(value);locations.append({'id':node.get('id'),'kind':node.tag,'start':offset,'end':offset+len(value)})
            offset+=len(value)+2
    if not chunks:raise ValueError('No article body or abstract text')
    doi=next((text(n) for n in root.findall('.//article-id') if n.get('pub-id-type')=='doi'),None)
    refs=[]
    for node in root.findall('.//ref//pub-id'):
        if node.get('pub-id-type')=='pmcid' and re.fullmatch(r'PMC\d+',text(node)):refs.append(text(node))
    return {'title':title,'text':'\n\n'.join(chunks),'url':f'https://europepmc.org/articles/{pmcid}',
            'study_id':doi or pmcid,'license_status':license_url,'origin':'europepmc_fulltext',
            'document':{'original_sha256':hashlib.sha256(raw).hexdigest(),'original_xml_base64':base64.b64encode(raw).decode('ascii'),'locations':locations,'references':list(dict.fromkeys(refs))[:20], 'license':license_url}}

def parse_bioc(raw: bytes, pmcid: str):
    import json
    if len(raw)>4_000_000:raise ValueError('BioC exceeds 4 MB budget')
    collections=json.loads(raw)
    if not isinstance(collections,list):raise ValueError('Unexpected BioC collection')
    documents=[d for collection in collections for d in collection.get('documents',[]) if d.get('id')==pmcid]
    if len(documents)!=1:raise ValueError('BioC document identity mismatch')
    document=documents[0]
    license_name=document.get('infons',{}).get('license','').strip().upper()
    if license_name not in {'CC BY','CC BY-SA','CC0'}:raise ValueError('Unsupported BioC reuse license')
    chunks=[];locations=[];offset=0;title=pmcid;doi=None
    for passage in document.get('passages',[]):
        info=passage.get('infons',{});value=passage.get('text','').strip()
        if not isinstance(value,str):raise ValueError('Invalid BioC text')
        if info.get('type')=='front':title=value or title
        doi=doi or info.get('article-id_doi')
        if not value or str(info.get('section_type','')).upper() in {'REF','REFERENCES'}:continue
        if offset+len(value)>250000:raise ValueError('Article text budget exceeded')
        chunks.append(value);locations.append({'kind':info.get('type','passage'),'section':info.get('section_type'),'source_offset':passage.get('offset'),'start':offset,'end':offset+len(value)})
        offset+=len(value)+2
    if not chunks:raise ValueError('No BioC text passages')
    return {'title':title[:500],'text':'\n\n'.join(chunks),'url':f'https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/',
            'study_id':doi or pmcid,'license_status':license_name+' (NCBI BioC license metadata)','origin':'ncbi_bioc_fulltext',
            'document':{'original_sha256':hashlib.sha256(raw).hexdigest(),'original_format':'bioc_json','original_content_base64':base64.b64encode(raw).decode('ascii'),'license':license_name,'locations':locations,'references':[]}}
