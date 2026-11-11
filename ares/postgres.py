"""PostgreSQL adapter with request-scoped RLS identity and native text search."""
from contextvars import ContextVar
from contextlib import contextmanager
import re
from .database import Database as SQLiteDatabase

PRINCIPAL=ContextVar('ares_principal',default='')

class Row(dict):
    def __getitem__(self,key):
        return list(self.values())[key] if isinstance(key,int) else super().__getitem__(key)
    def __iter__(self):return iter(self.values())

class Cursor:
    def __init__(self,cursor):self.cursor=cursor
    def fetchone(self):
        row=self.cursor.fetchone();return Row(row) if row is not None else None
    def fetchall(self):return [Row(row) for row in self.cursor.fetchall()]
    def __iter__(self):return iter(self.fetchall())

class Connection:
    is_postgres=True
    def __init__(self,connection):self.connection=connection
    def execute(self,sql,parameters=()):
        if sql.strip()=='BEGIN IMMEDIATE':sql='SELECT 1'
        sql=sql.replace('ORDER BY p.rowid DESC','ORDER BY p.id DESC').replace('ORDER BY rowid LIMIT','ORDER BY run_id LIMIT')
        ignore=bool(re.search(r'INSERT OR IGNORE',sql,re.I))
        sql=re.sub(r'INSERT OR IGNORE','INSERT',sql,flags=re.I)
        if ignore:sql=sql.rstrip().rstrip(';')+' ON CONFLICT DO NOTHING'
        if 'INSERT OR REPLACE INTO embeddings' in sql:
            sql=sql.replace('INSERT OR REPLACE','INSERT')+' ON CONFLICT(passage_id,model) DO UPDATE SET vector=excluded.vector,text_hash=excluded.text_hash'
        sql=sql.replace('?', '%s')
        return Cursor(self.connection.execute(sql,parameters))

class PostgresDatabase(SQLiteDatabase):
    def __init__(self,dsn):
        self.dsn=dsn
        # Schema must be provisioned by a separate administrative migration command.
        with self.connect() as db:
            role=db.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            owns=db.execute("SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner WHERE c.relname='sources' AND r.rolname=current_user").fetchone()[0]
            if role['rolsuper'] or role['rolbypassrls'] or owns:
                raise ValueError('Runtime database role must not own tables or bypass row-level security')
            db.execute('SELECT version FROM schema_versions LIMIT 1').fetchone()
    @contextmanager
    def connect(self):
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(self.dsn,row_factory=dict_row,connect_timeout=10) as connection:
            connection.execute("SELECT set_config('ares.user',%s,true)",(PRINCIPAL.get(),))
            connection.execute("SET LOCAL statement_timeout='30s'")
            yield Connection(connection)
    def index_source(self,db,source):
        text=source['text']
        for start in range(0,len(text),900):
            end=min(start+1000,len(text))
            db.execute('INSERT OR IGNORE INTO passages VALUES(?,?,?,?,?,?)',(f"{source['id']}:{start}",source['id'],source['project_id'],start,end,text[start:end]))
    def search(self,db,project_id,question,limit=8):
        from .database import STOPWORDS
        terms=list(dict.fromkeys(t.lower() for t in re.findall(r'\w+',question) if len(t)>2 and t.lower() not in STOPWORDS))[:30]
        if not terms:return []
        query=' | '.join(terms)
        return [dict(r) for r in db.execute('''SELECT p.*,s.url,s.digest,s.license_status,s.created_at AS retrieved_at,
            coalesce(d.title,s.url) AS title,coalesce(d.study_id,s.url) AS study_id,coalesce(d.origin,'user_supplied') AS origin,
            coalesce((SELECT max(id) FROM source_reviews WHERE source_id=s.id),0) AS review_version,
            -ts_rank_cd(to_tsvector('english',p.text),to_tsquery('english',?)) AS rank
            FROM passages p JOIN sources s ON s.id=p.source_id LEFT JOIN source_details d ON d.source_id=s.id
            WHERE p.project_id=? AND to_tsvector('english',p.text) @@ to_tsquery('english',?)
            AND coalesce((SELECT status FROM source_reviews WHERE source_id=s.id ORDER BY id DESC LIMIT 1),'active')='active'
            ORDER BY rank,p.id LIMIT ?''',(query,project_id,query,limit))]
