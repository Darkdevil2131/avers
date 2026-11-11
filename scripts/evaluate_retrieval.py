import json
import tempfile
from pathlib import Path
from ares.database import Database
from ares.retrieval import hybrid_search

CASES=[
 ('A car burns gasoline to power its internal combustion engine.','Which fuel powers an automobile?'),
 ('The canine was examined by a veterinarian for an injured paw.','Who treated the dog foot injury?'),
 ('A photovoltaic panel converts sunlight into electrical energy.','How do solar cells generate electricity?'),
 ('Patients with hypertension had elevated systolic blood pressure.','What measurement is raised in high blood pressure?'),
 ('The alloy corroded rapidly when immersed in salt water.','What happens to metal exposed to saline liquid?'),
 ('Seedlings grew taller when supplied with nitrogen fertilizer.','What nutrient increased young plant height?'),
 ('The spacecraft used solar radiation to generate onboard power.','How did the satellite obtain electrical supply?'),
 ('Antibiotic treatment reduced the number of bacterial colonies.','What intervention lowered bacterial growth?'),
 ('Insulation reduced heat loss through the building walls.','What kept thermal energy inside the house?'),
 ('Memory usage increased as the program stored additional arrays.','What resource grew when software retained more data?')]
with tempfile.TemporaryDirectory() as directory:
 dbs=Database(Path(directory)/'eval.db')
 with dbs.connect() as db:
  db.execute("INSERT INTO projects VALUES('p','evaluation','Synthetic evaluation')")
  ids=[]
  for i,(text,_) in enumerate(CASES):
   ids.append(dbs.add_source(db,'p',{'url':f'https://example.org/synthetic/{i}','title':f'Synthetic {i}','text':text,'license_status':'synthetic evaluation fixture'},'evaluation')['id'])
  result=[]
  for i,(_,q) in enumerate(CASES):
   lexical=dbs.search(db,'p',q,limit=3)
   hybrid,status=hybrid_search(dbs,db,'p',q,limit=3)
   result.append({'case':i,'lexical_top1':bool(lexical and lexical[0]['source_id']==ids[i]),'hybrid_top1':bool(hybrid and hybrid[0]['source_id']==ids[i]),'hybrid_recall3':any(r['source_id']==ids[i] for r in hybrid),'mode':status['mode']})
 print(json.dumps({'dataset':'10 synthetic paraphrase cases authored during implementation; not held-out scientific validation','results':result,'lexical_top1':sum(x['lexical_top1'] for x in result)/len(result),'hybrid_top1':sum(x['hybrid_top1'] for x in result)/len(result),'hybrid_recall3':sum(x['hybrid_recall3'] for x in result)/len(result)},indent=2))
