"""Forward-only schema sync: creates missing tables and ADDs missing columns (SQLite and PostgreSQL).
Not a replacement for Alembic on destructive changes (renames/drops), which must be written by hand."""
from sqlalchemy import inspect, text


def install_guards(engine):
    """Database-level invariant: belief history is append-only (the spec's provenance rule, enforced by the database, not only by code).
    SQLite version is tested. The PostgreSQL version is written to the same rule but has NOT been run against a real PostgreSQL server."""
    with engine.begin() as cx:
        if engine.dialect.name == "sqlite":
            for op in ("UPDATE", "DELETE"):
                cx.execute(text(f"CREATE TRIGGER IF NOT EXISTS belief_events_no_{op.lower()} BEFORE {op} ON belief_events "
                                "BEGIN SELECT RAISE(ABORT, 'belief_events is append-only'); END"))
        elif engine.dialect.name == "postgresql":
            cx.execute(text("CREATE OR REPLACE FUNCTION forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$ "
                            "BEGIN RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME; END $$"))
            cx.execute(text("DROP TRIGGER IF EXISTS belief_events_append_only ON belief_events"))
            cx.execute(text("CREATE TRIGGER belief_events_append_only BEFORE UPDATE OR DELETE ON belief_events "
                            "FOR EACH ROW EXECUTE FUNCTION forbid_change()"))
        stmts = GUARD_SQL_SQLITE if engine.dialect.name == "sqlite" else GUARD_SQL_PG if engine.dialect.name == "postgresql" else []
        for sql in stmts:
            cx.execute(text(sql))


GUARD_SQL_SQLITE = [
    "CREATE TRIGGER IF NOT EXISTS claims_need_text BEFORE INSERT ON claims WHEN trim(coalesce(NEW.text, '')) = '' "
    "BEGIN SELECT RAISE(ABORT, 'claim has no text'); END",
    "CREATE TRIGGER IF NOT EXISTS evidence_needs_source BEFORE INSERT ON evidence_items "
    "WHEN NEW.paper_id IS NULL AND trim(coalesce(NEW.doi, '')) = '' AND trim(coalesce(NEW.title, '')) = '' "
    "BEGIN SELECT RAISE(ABORT, 'evidence has no source (paper, doi or title)'); END",
]
GUARD_SQL_PG = [
    "CREATE OR REPLACE FUNCTION require_claim_text() RETURNS trigger LANGUAGE plpgsql AS $$ "
    "BEGIN IF btrim(coalesce(NEW.text, '')) = '' THEN RAISE EXCEPTION 'claim has no text'; END IF; RETURN NEW; END $$",
    "DROP TRIGGER IF EXISTS claims_need_text ON claims",
    "CREATE TRIGGER claims_need_text BEFORE INSERT ON claims FOR EACH ROW EXECUTE FUNCTION require_claim_text()",
    "CREATE OR REPLACE FUNCTION require_evidence_source() RETURNS trigger LANGUAGE plpgsql AS $$ "
    "BEGIN IF NEW.paper_id IS NULL AND btrim(coalesce(NEW.doi, '')) = '' AND btrim(coalesce(NEW.title, '')) = '' "
    "THEN RAISE EXCEPTION 'evidence has no source (paper, doi or title)'; END IF; RETURN NEW; END $$",
    "DROP TRIGGER IF EXISTS evidence_needs_source ON evidence_items",
    "CREATE TRIGGER evidence_needs_source BEFORE INSERT ON evidence_items FOR EACH ROW EXECUTE FUNCTION require_evidence_source()",
]


def ensure_schema(engine, Base):
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as cx:
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    cx.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'))
    install_guards(engine)
