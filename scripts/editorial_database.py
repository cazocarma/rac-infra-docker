"""Explicit editorial DB provisioning, separate from staff/account fixtures.

Does not enable a listener, configure Keycloak, publish text or activate policy.
"""
from urllib.parse import urlsplit, unquote, parse_qs
import re
import uuid
from database_roles import validate_credentials


SIGNATURES = (
    'documents.draft_document(audit.reference,audit.reference,audit.reference,audit.reference,text,text,text,text,boolean,audit.digest)',
    'documents.review_document(audit.reference,audit.reference,audit.reference,audit.reference,audit.digest,text)',
    'documents.publish_document(audit.reference,audit.reference,audit.reference,audit.reference,audit.digest)',
    'documents.read_editorial_document(uuid)',
    'documents.editorial_ready()',
    'documents.draft_assessment(audit.reference,audit.reference,audit.reference,audit.reference,text,text,text,audit.digest)',
    'documents.review_assessment(audit.reference,audit.reference,audit.reference,audit.reference,audit.digest,text)',
    'documents.publish_assessment(audit.reference,audit.reference,audit.reference,audit.reference,audit.digest)',
    'documents.read_editorial_assessment(uuid)',
    'documents.activate_editorial_bundle(audit.reference,bigint,text,uuid[],text[],audit.reference,audit.digest,audit.reference,audit.reference,text[])',
    'documents.read_editorial_registry(text)',
)


def validate_target(dsn, database, role):
    if role not in ('rac_documents_editorial', 'rac_editorial_lab') or not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', database) or database in ('postgres', 'keycloak'):
        raise RuntimeError('Dedicated editorial database identity required')
    try:
        parsed = urlsplit(dsn)
        options = parse_qs(parsed.query, strict_parsing=True)
        valid = (parsed.scheme in ('postgres', 'postgresql') and parsed.hostname == 'postgres'
                 and parsed.port in (None, 5432) and unquote(parsed.username or '') == role
                 and parsed.path == '/' + database and not parsed.fragment
                 and options == {'sslmode': ['disable']}
                 and len(unquote(parsed.password or '')) >= 24)
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise RuntimeError('Exact internal DEV editorial connection required')
    return unquote(parsed.password)


def validate_environment(values):
    """Validate all configured identities before opening an operator connection."""
    if values.get('RAC_ENV') != 'dev':
        raise RuntimeError('Explicit DEV provisioning only')
    dsn, database = values.get('DOCUMENT_EDITORIAL_DATABASE_URL', ''), values.get('POSTGRES_DB', '')
    password = validate_target(dsn, database, 'rac_documents_editorial')
    existing = set(validate_credentials(values).values())
    existing.update(values[key] for key in ('PGPASSWORD', 'POSTGRES_PASSWORD', 'KEYCLOAK_DB_PASSWORD') if values.get(key))
    if password in existing:
        raise RuntimeError('Independent editorial secret required')
    return dsn, database


def provision(db, dsn, database, role='rac_documents_editorial'):
    """Caller owns the operator transaction; only exact capabilities are granted.

    Current transport is the internal DEV network. QA/PRD TLS/operator workflows
    require a separately reviewed adapter, not silent SSL downgrades here.
    """
    from psycopg import sql
    password = validate_target(dsn, database, role)
    current, superuser = db.execute('SELECT current_database(),rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()
    if current != database or not superuser:
        raise RuntimeError('Matching editorial operator transaction required')
    db.execute("SET LOCAL lock_timeout='2s'")
    db.execute("SET LOCAL statement_timeout='5s'")
    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('rac-editorial-provision:' + role,))
    for signature in SIGNATURES:
        if db.execute('SELECT to_regprocedure(%s)', (signature,)).fetchone()[0] is None:
            raise RuntimeError('Editorial schema capabilities are incomplete')
    existing = db.execute('SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
    if existing and any(existing):
        raise RuntimeError('Refusing privileged editorial identity')
    if db.execute('SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=%s', (role,)).fetchone():
        raise RuntimeError('Refusing inherited editorial authority')
    if existing:
        excessive = db.execute("""SELECT EXISTS(SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname IN('public','documents','audit','standing') AND c.relkind IN('r','p','v','m','f')
          AND NOT EXISTS(SELECT FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
          AND (has_table_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               OR has_any_column_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,REFERENCES')))""", (role, role)).fetchone()[0]
        if excessive:
            raise RuntimeError('Refusing editorial table authority')
        if db.execute("SELECT EXISTS(SELECT FROM pg_namespace WHERE nspname IN('public','documents','audit','standing') AND has_schema_privilege(%s,oid,'CREATE'))", (role,)).fetchone()[0]:
            raise RuntimeError('Refusing editorial schema authority')
        for forbidden in ('documents.activate(uuid,bigint,text,uuid[],uuid,uuid,text[])',
                          'documents.editorial_record(uuid,uuid,uuid,uuid,text,jsonb)'):
            if db.execute('SELECT has_function_privilege(%s,%s,\'EXECUTE\')', (role, forbidden)).fetchone()[0]:
                raise RuntimeError('Refusing raw editorial authority')
    else:
        db.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
    db.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
    db.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(database), sql.Identifier(role)))
    db.execute(sql.SQL('GRANT USAGE ON SCHEMA public,documents,audit TO {}').format(sql.Identifier(role)))
    for signature in SIGNATURES:
        # Fixed reviewed signature, never caller-supplied SQL/catalog overloads.
        db.execute(sql.SQL('GRANT EXECUTE ON FUNCTION ' + signature + ' TO {}').format(sql.Identifier(role)))
    writer = db.execute('SELECT actor_id,chain_id FROM audit.writer_principals WHERE database_role=%s', (role,)).fetchone()
    if writer is None:
        chain, actor = uuid.uuid4(), uuid.uuid4()
        db.execute('INSERT INTO audit.chain_heads(chain_id) VALUES(%s)', (chain,))
        db.execute('INSERT INTO audit.writer_principals(database_role,actor_id,chain_id) VALUES(%s,%s,%s)', (role, actor, chain))


if __name__ == '__main__':
    import os
    import psycopg
    try:
        dsn, database = validate_environment(os.environ)
        with psycopg.connect() as operator:
            provision(operator, dsn, database)
        with psycopg.connect(dsn) as editorial:
            if editorial.execute('SELECT current_user,documents.editorial_ready()').fetchone() != ('rac_documents_editorial', True):
                raise RuntimeError('Editorial connection not ready')
    except Exception:
        raise SystemExit('Editorial provisioning failed; credentials and server diagnostics were not printed') from None
    print('Editorial DEV database identity ready; access flags and staff accounts unchanged')
