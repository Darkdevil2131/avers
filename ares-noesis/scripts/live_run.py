"""Run Noesis on a REAL paper with REAL network calls (no mocks).
Usage (from repo root, on a machine with internet):
   python scripts/live_run.py path/to/paper.pdf [--email you@uni.edu] [--ads-token TOKEN]
Prints exactly what each connector returned, so nothing hides behind tests."""
import argparse, sys
sys.path.insert(0, ".")
from sqlalchemy import select
from noesis.config import Settings
from noesis.connectors.sources import default_connectors
from noesis.db import make_engine, make_session_factory
from noesis.ingestion.parse import sha256_hex
from noesis.models import Document, Job, Project, Report
from noesis.pipeline import analyze_document
from noesis.storage import LocalBlobStore

ap = argparse.ArgumentParser()
ap.add_argument("pdf"); ap.add_argument("--email", default=""); ap.add_argument("--ads-token", default="")
a = ap.parse_args()
st = Settings(database_url="sqlite:///./noesis_live.db", data_dir="./data_live", contact_email=a.email, ads_token=a.ads_token)
sf = make_session_factory(make_engine(st.database_url)); store = LocalBlobStore(st.data_dir)

print("== connector reachability (real HTTP) ==")
conns = default_connectors(st)
for name, c in conns.items():
    try:
        r = c.search("graphene battery degradation", 2)
        print(f"{name:10s} OK    {len(r)} results; first: {r[0].title[:70] if r else '-'}")
    except Exception as e:
        print(f"{name:10s} FAIL  {type(e).__name__}: {e}")

data = open(a.pdf, "rb").read(); name = a.pdf.replace("\\", "/").split("/")[-1]; s = sf()
p = Project(name="live"); s.add(p); s.flush()
key = f"projects/{p.id}/originals/{sha256_hex(data)}/{name}"; store.put(key, data)
d = Document(project_id=p.id, filename=name, sha256=sha256_hex(data), blob_key=key); s.add(d); s.flush()
j = Job(project_id=p.id, document_id=d.id); s.add(j); s.commit()
res = analyze_document(sf, store, st, j.id, conns)
print("\n== task results ==")
for k, v in res["tasks"].items():
    print(f"{k:22s} {v['status']:10s} {v.get('error', '')}")
print("\n" + s.scalars(select(Report).order_by(Report.id.desc())).first().markdown)
