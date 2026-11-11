from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="researcher")  # admin | researcher
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("project_id", "sha256"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64))
    blob_key: Mapped[str] = mapped_column(String(400))
    status: Mapped[str] = mapped_column(String(30), default="uploaded")
    n_pages: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str] = mapped_column(String(60), default="")
    kind: Mapped[str] = mapped_column(String(30))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class ExternalPaper(Base):
    __tablename__ = "external_papers"
    __table_args__ = (UniqueConstraint("project_id", "content_hash"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(200), default="")
    doi: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str] = mapped_column(Text, default="")
    license: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    retracted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_preprint: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Belief(Base):
    __tablename__ = "beliefs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    claim_id: Mapped[Optional[int]] = mapped_column(ForeignKey("claims.id"), nullable=True)
    claim_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    assessment: Mapped[str] = mapped_column(String(40), default="insufficient_evidence")
    support_class: Mapped[str] = mapped_column(String(40), default="unsupported")
    posterior: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    uncertainty: Mapped[str] = mapped_column(String(20), default="high")
    n_effective: Mapped[int] = mapped_column(Integer, default=0)
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    belief_id: Mapped[int] = mapped_column(ForeignKey("beliefs.id"), index=True)
    paper_id: Mapped[Optional[int]] = mapped_column(ForeignKey("external_papers.id"), nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(60), default="")
    doi: Mapped[str] = mapped_column(String(200), default="")
    design: Mapped[str] = mapped_column(String(40), default="unknown")
    stance: Mapped[str] = mapped_column(String(20), default="neutral")
    sample_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    peer_reviewed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    retracted: Mapped[bool] = mapped_column(Boolean, default=False)
    independence_group: Mapped[str] = mapped_column(String(200), default="")
    grade: Mapped[int] = mapped_column(Integer, default=1)
    grade_label: Mapped[str] = mapped_column(String(20), default="very_low")
    criteria: Mapped[list] = mapped_column(JSON, default=list)
    method: Mapped[str] = mapped_column(String(80), default="")
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class BeliefEvent(Base):
    __tablename__ = "belief_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    belief_id: Mapped[int] = mapped_column(ForeignKey("beliefs.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text, default="")
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="candidate")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    document_id: Mapped[Optional[int]] = mapped_column(ForeignKey("documents.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), default="analyze_document")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    attempts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(80), default="system")
    action: Mapped[str] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    markdown: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CorpusPaper(Base):
    """Global, deduplicated literature corpus harvested from real sources (shared by all projects)."""
    __tablename__ = "corpus_papers"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(200), default="")
    doi: Mapped[str] = mapped_column(String(200), default="", index=True)
    title: Mapped[str] = mapped_column(Text)
    abstract: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    authors: Mapped[list] = mapped_column(JSON, default=list)
    venue: Mapped[str] = mapped_column(String(300), default="")
    license: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    open_access_pdf: Mapped[str] = mapped_column(String(500), default="")
    retracted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_preprint: Mapped[bool] = mapped_column(Boolean, default=False)
    cited_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pub_types: Mapped[list] = mapped_column(JSON, default=list)
    sample_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    domain: Mapped[str] = mapped_column(String(30), default="", index=True)
    design: Mapped[str] = mapped_column(String(40), default="unknown")
    triples: Mapped[list] = mapped_column(JSON, default=list)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    query: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(30), default="")
    status: Mapped[str] = mapped_column(String(20), default="running")
    n_fetched: Mapped[int] = mapped_column(Integer, default=0)
    n_new: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Concept(Base):
    """A controlled-vocabulary term loaded from a real ontology file (OBO). Nothing is seeded by default."""
    __tablename__ = "concepts"
    __table_args__ = (UniqueConstraint("ontology", "term_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ontology: Mapped[str] = mapped_column(String(60), index=True)
    term_id: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(Text)
    definition: Mapped[str] = mapped_column(Text, default="")
    synonyms: Mapped[list] = mapped_column(JSON, default=list)
    parents: Mapped[list] = mapped_column(JSON, default=list)
    obsolete: Mapped[bool] = mapped_column(default=False)
