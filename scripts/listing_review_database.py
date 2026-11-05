"""Explicit listing review DB provisioning: three separate function-only logins.

Does not enable a listener, configure Keycloak, create staff accounts, seed a
reason catalog or approve D04 categories. Reader, corrector and approver never
share a credential: reading content, rejecting and approving stay separable.
"""
from urllib.parse import urlsplit, unquote, parse_qs
import re
import uuid
from database_roles import validate_credentials

READY = 'listing_review.ready()'
INGRESSES = {
    'rac_listing_reader': ('LISTING_REVIEW_READER_DATABASE_URL', (
        READY,
        'listing_review.queue(audit.reference,audit.reference,audit.reference,integer,integer,timestamp with time zone,uuid)',
        'listing_review.revision(audit.reference,audit.reference,audit.reference,audit.reference)',
        'listing_review.photo(audit.reference,audit.reference,audit.reference,audit.reference)',
    )),
    'rac_listing_corrector': ('LISTING_REVIEW_CORRECTOR_DATABASE_URL', (
        READY,
        'listing_review.correct(audit.reference,audit.reference,audit.reference,audit.reference,bigint,audit.digest,text,text,text)',
        'listing_review.correction_ready()',
    )),
    'rac_listing_approver': ('LISTING_REVIEW_APPROVER_DATABASE_URL', (
        READY,
        'listing_review.approval_context(audit.reference,audit.reference,bigint,audit.digest)',
        'listing_review.approve(audit.reference,audit.reference,audit.reference,audit.reference,bigint,audit.digest,text,jsonb,boolean)',
    )),
}
SCHEMAS = ('public', 'listing_review', 'audit', 'standing', 'documents', 'photo')


def validate_target(dsn, database, role):
    if role not in INGRESSES or not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', database) or database in ('postgres', 'keycloak'):
        raise RuntimeError('Dedicated listing review database identity required')
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
        raise RuntimeError('Exact internal DEV listing review connection required')
    return unquote(parsed.password)


def validate_environment(values):
    """Validate all three identities before opening an operator connection."""
    if values.get('RAC_ENV') != 'dev':
        raise RuntimeError('Explicit DEV provisioning only')
    database = values.get('POSTGRES_DB', '')
    existing = set(validate_credentials(values).values())
    existing.update(values[key] for key in ('PGPASSWORD', 'POSTGRES_PASSWORD', 'KEYCLOAK_DB_PASSWORD') if values.get(key))
    if values.get('DOCUMENT_EDITORIAL_DATABASE_URL'):
        existing.add(unquote(urlsplit(values['DOCUMENT_EDITORIAL_DATABASE_URL']).password or ''))
    targets = {}
    for role, (variable, _) in INGRESSES.items():
        dsn = values.get(variable, '')
        password = validate_target(dsn, database, role)
        if password in existing:
            raise RuntimeError('Independent listing review secret required')
        existing.add(password)
        targets[role] = dsn
    return targets, database


def provision(db, dsn, database, role):
    """Caller owns the operator transaction; only exact capabilities are granted."""
    from psycopg import sql
    password = validate_target(dsn, database, role)
    signatures = INGRESSES[role][1]
    current, superuser = db.execute('SELECT current_database(),rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()
    if current != database or not superuser:
        raise RuntimeError('Matching listing review operator transaction required')
    db.execute("SET LOCAL lock_timeout='2s'")
    db.execute("SET LOCAL statement_timeout='5s'")
    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('rac-listing-review-provision:' + role,))
    capabilities = []
    for signature in signatures:
        capability = db.execute('SELECT to_regprocedure(%s)::oid', (signature,)).fetchone()[0]
        if capability is None:
            raise RuntimeError('Listing review schema capabilities are incomplete')
        capabilities.append(capability)
    existing = db.execute('SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
    if existing and any(existing):
        raise RuntimeError('Refusing privileged listing review identity')
    if db.execute('SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=%s', (role,)).fetchone():
        raise RuntimeError('Refusing inherited listing review authority')
    if existing:
        unexpected = db.execute("""SELECT EXISTS(SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) acl
          JOIN pg_roles principal ON principal.oid=acl.grantee
          WHERE principal.rolname=%s AND n.nspname=ANY(%s)
          AND acl.privilege_type='EXECUTE' AND NOT(p.oid=ANY(%s::oid[])))""", (role, list(SCHEMAS), capabilities)).fetchone()[0]
        if unexpected:
            raise RuntimeError('Refusing unexpected listing review function authority')
        excessive = db.execute("""SELECT EXISTS(SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname=ANY(%s) AND c.relkind IN('r','p','v','m','f','S')
          AND NOT EXISTS(SELECT FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
          AND (has_table_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               OR has_any_column_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,REFERENCES')))""", (list(SCHEMAS), role, role)).fetchone()[0]
        if excessive:
            raise RuntimeError('Refusing listing review table authority')
        if db.execute("SELECT EXISTS(SELECT FROM pg_namespace WHERE nspname=ANY(%s) AND has_schema_privilege(%s,oid,'CREATE'))", (list(SCHEMAS), role)).fetchone()[0]:
            raise RuntimeError('Refusing listing review schema authority')
    else:
        db.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
    db.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
    db.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(database), sql.Identifier(role)))
    db.execute(sql.SQL('GRANT USAGE ON SCHEMA listing_review,audit TO {}').format(sql.Identifier(role)))
    for signature in signatures:
        # Fixed reviewed signature, never caller-supplied SQL/catalog overloads.
        db.execute(sql.SQL('GRANT EXECUTE ON FUNCTION ' + signature + ' TO {}').format(sql.Identifier(role)))
    if db.execute('SELECT 1 FROM audit.writer_principals WHERE database_role=%s', (role,)).fetchone() is None:
        chain, actor = uuid.uuid4(), uuid.uuid4()
        db.execute('INSERT INTO audit.chain_heads(chain_id) VALUES(%s)', (chain,))
        db.execute('INSERT INTO audit.writer_principals(database_role,actor_id,chain_id) VALUES(%s,%s,%s)', (role, actor, chain))


if __name__ == '__main__':
    import os
    import psycopg
    try:
        targets, database = validate_environment(os.environ)
        with psycopg.connect() as operator:
            for role, dsn in targets.items():
                provision(operator, dsn, database, role)
        for role, dsn in targets.items():
            with psycopg.connect(dsn) as ingress:
                if ingress.execute('SELECT current_user,listing_review.ready()').fetchone() != (role, True):
                    raise RuntimeError('Listing review connection not ready')
    except Exception:
        raise SystemExit('Listing review provisioning failed; credentials and server diagnostics were not printed') from None
    print('Listing review DEV database identities ready; access flags, staff accounts and reason catalogs unchanged')
