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
