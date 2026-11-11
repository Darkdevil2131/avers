"""Provision runtime credentials from private environment, never logs their values."""
import os
import psycopg
from psycopg import sql
with psycopg.connect(os.environ['ARES_ADMIN_DATABASE']) as db:
    for role,key in [('ares_app','ARES_DB_APP_PASSWORD'),('ares_worker','ARES_DB_WORKER_PASSWORD')]:
        password=os.environ[key]
        if len(password)<32:raise SystemExit('Runtime role passwords must contain at least 32 characters')
        db.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(role),sql.Literal(password)))
print('Configured separate runtime credentials')
