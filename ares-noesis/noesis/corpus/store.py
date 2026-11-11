"""Corpus harvesting: real sources -> deduplicated CorpusPaper rows with provenance, license, design, triples."""
from datetime import datetime, timezone

from sqlalchemy import func, select

from ..agents.domain_agents import AGENT_CLASSES
from ..connectors.base import ConnectorError, ConnectorUnavailable, Paper
from ..ingestion.claims import extract_triple
from ..ingestion.parse import split_sentences
from ..models import CorpusPaper, SyncRun


NON_EVIDENCE = {"grant", "patent", "dataset"}   # record types that are context, not scientific evidence


def upsert(s, papers: list, domain: str, topic: str) -> int:
    """Insert new papers (dedupe by DOI/title hash). Existing rows only gain the topic tag. Returns #new."""
    agent = AGENT_CLASSES.get(domain, AGENT_CLASSES["technology"])({})
    new = 0
    for p in papers:
        if not p.title or not (p.abstract or p.doi):
            continue  # nothing usable to reason over
        row = s.scalars(select(CorpusPaper).where(CorpusPaper.content_hash == p.content_hash)).first()
        if row:
            if topic not in row.topics:
                row.topics = list(row.topics) + [topic]
            if row.retracted is None and p.retracted is not None:
                row.retracted = p.retracted
            continue
        triples = [t for sent in split_sentences(p.abstract) if (t := extract_triple(sent))]
        s.add(CorpusPaper(
            content_hash=p.content_hash, source=p.source, source_id=p.source_id, doi=p.doi, title=p.title,
            abstract=p.abstract, year=p.year, authors=p.authors[:10], venue=p.venue, license=p.license, url=p.url,
            open_access_pdf=p.open_access_pdf, retracted=p.retracted, is_preprint=p.is_preprint, cited_by=p.cited_by,
            pub_types=p.pub_types, sample_size=p.sample_size, domain=domain, design="non_evidence" if set(t.lower() for t in p.pub_types) & NON_EVIDENCE else agent.classify(p), triples=triples, topics=[topic],
            retrieved_at=datetime.now(timezone.utc)))
        new += 1
    s.flush()
    return new


def sync_topic(sf, connectors: dict, topic: str, domain: str, sources: list, limit: int = 100, per_page: int = 25) -> list:
    """Harvest up to `limit` papers per source for a topic. Every source attempt is recorded in sync_runs (success or failure)."""
    out = []
    for name in sources:
        conn = connectors.get(name)
        s = sf()
        run = SyncRun(source=name, query=topic, domain=domain)
        s.add(run)
        s.commit()
        try:
            if conn is None:
                raise ConnectorUnavailable(name, "unknown source")
            page = 1
            while run.n_fetched < limit:
                batch = conn.search(topic, min(per_page, limit - run.n_fetched), page)
                if not batch:
                    break
                run.n_fetched += len(batch)
                run.n_new += upsert(s, batch, domain, topic)
                s.commit()
                page += 1
            run.status = "ok"
        except (ConnectorUnavailable, ConnectorError) as e:
            s.rollback()
            run = s.get(SyncRun, run.id)
            run.status, run.error = "failed", str(e)
        run.finished_at = datetime.now(timezone.utc)
        s.commit()
        out.append({"source": name, "status": run.status, "fetched": run.n_fetched, "new": run.n_new, "error": run.error})
        s.close()
    return out


def stats(s) -> dict:
    total = s.scalar(select(func.count(CorpusPaper.id)))
    by = lambda col: {k or "": v for k, v in s.execute(select(col, func.count(CorpusPaper.id)).group_by(col))}
    return {"total": total, "by_source": by(CorpusPaper.source), "by_domain": by(CorpusPaper.domain), "by_design": by(CorpusPaper.design),
            "with_abstract": s.scalar(select(func.count(CorpusPaper.id)).where(CorpusPaper.abstract != "")),
            "retracted": s.scalar(select(func.count(CorpusPaper.id)).where(CorpusPaper.retracted.is_(True)))}
