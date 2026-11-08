"""Explicit DEV provisioning of the Trust & Safety function-only logins.

Three separate identities: the staff case console (admin), the effect relay
(admin, ts.outbox -> broker) and the effect consumer (user, broker -> standing).
None of them shares a credential or a capability beyond what its process
checks with CheckRole. This does not create staff accounts, Keycloak roles,
broker credentials, retention policies or customer intake; it does not apply
migrations and refuses anything other than RAC_ENV=dev.
"""
from urllib.parse import urlsplit, unquote, parse_qs
import re
import uuid
from database_roles import validate_credentials

REF = 'audit.reference,audit.reference,audit.reference'
LOGINS = {
    'rac_ts_cases': ('TS_CASES_DATABASE_URL', ('ts', 'audit'), (
        f'ts.case_queue({REF},integer)',
        f'ts.case_detail({REF},uuid)',
        f'ts.case_assign({REF},uuid,audit.reference)',
        f'ts.action_propose({REF},uuid,text,text,text,integer,text)',
        f'ts.listing_hide_propose({REF},uuid,uuid,text,text,text)',
        f'ts.action_approve({REF},uuid)',
        f'ts.action_revoke({REF},uuid,text)',
        f'ts.appeal_decide({REF},uuid,text)',
    )),
    'rac_ts_relay': ('TS_RELAY_DATABASE_URL', ('ts', 'audit'), (
        'ts.effect_relay_ready()',
        'ts.claim_effect(audit.reference)',
        'ts.confirm_effect(audit.reference)',
        'ts.retry_effect(audit.reference)',
        'ts.effect_relay_backlog()',
    )),
    'rac_ts_effects': ('TS_EFFECTS_DATABASE_URL', ('standing',), (
        'standing.apply_ts_effect(uuid,jsonb,uuid)',
        'standing.refresh_ts_standing(uuid,uuid,uuid)',
        'standing.ts_expiries_due(integer)',
    )),
}
SCHEMAS = ('public', 'ts', 'audit', 'standing', 'listing_review', 'documents', 'photo')


def validate_target(dsn, database, role):
    if role not in LOGINS or not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', database) or database in ('postgres', 'keycloak'):
        raise RuntimeError('Dedicated T&S database identity required')
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
        raise RuntimeError('Exact internal DEV T&S connection required')
    return unquote(parsed.password)


def validate_environment(values):
    """Validate every requested identity before opening an operator connection.

    Only logins whose variable is present are provisioned, so the console and
    the effect transport can be enabled independently.
    """
    if values.get('RAC_ENV') != 'dev':
        raise RuntimeError('Explicit DEV provisioning only')
    database = values.get('POSTGRES_DB', '')
    existing = set(validate_credentials(values).values())
    existing.update(values[key] for key in ('PGPASSWORD', 'POSTGRES_PASSWORD', 'KEYCLOAK_DB_PASSWORD') if values.get(key))
    for key, value in values.items():
        if key.endswith('_DATABASE_URL') and value and key not in {variable for variable, _, _ in LOGINS.values()}:
            try:
                existing.add(unquote(urlsplit(value).password or ''))
            except ValueError:
                raise RuntimeError('Unreadable sibling database identity') from None
    existing.discard('')
    targets = {}
    for role, (variable, _, _) in LOGINS.items():
        dsn = values.get(variable, '')
        if not dsn:
            continue
        password = validate_target(dsn, database, role)
        if password in existing:
            raise RuntimeError('Independent T&S secret required')
        existing.add(password)
        targets[role] = dsn
    if not targets:
        raise RuntimeError('No T&S identity requested')
    return targets, database


def provision(db, dsn, database, role):
    """Caller owns the operator transaction; only exact capabilities are granted."""
    from psycopg import sql
    password = validate_target(dsn, database, role)
    _, schemas, signatures = LOGINS[role]
    current, superuser = db.execute('SELECT current_database(),rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()
    if current != database or not superuser:
        raise RuntimeError('Matching T&S operator transaction required')
    db.execute("SET LOCAL lock_timeout='2s'")
    db.execute("SET LOCAL statement_timeout='5s'")
    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('rac-ts-provision:' + role,))
    capabilities = []
    for signature in signatures:
        capability = db.execute('SELECT to_regprocedure(%s)::oid', (signature,)).fetchone()[0]
        if capability is None:
            raise RuntimeError('T&S schema capabilities are incomplete; apply migrations first')
        capabilities.append(capability)
    existing = db.execute('SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
    if existing and any(existing):
        raise RuntimeError('Refusing privileged T&S identity')
    if db.execute('SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=%s', (role,)).fetchone():
        raise RuntimeError('Refusing inherited T&S authority')
    if existing:
        unexpected = db.execute("""SELECT EXISTS(SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          CROSS JOIN LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) acl
          JOIN pg_roles principal ON principal.oid=acl.grantee
          WHERE principal.rolname=%s AND n.nspname=ANY(%s)
          AND acl.privilege_type='EXECUTE' AND NOT(p.oid=ANY(%s::oid[])))""", (role, list(SCHEMAS), capabilities)).fetchone()[0]
        if unexpected:
            raise RuntimeError('Refusing unexpected T&S function authority')
        excessive = db.execute("""SELECT EXISTS(SELECT FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname=ANY(%s) AND c.relkind IN('r','p','v','m','f','S')
          AND NOT EXISTS(SELECT FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
          AND (has_table_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               OR has_any_column_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,REFERENCES')))""", (list(SCHEMAS), role, role)).fetchone()[0]
        if excessive:
            raise RuntimeError('Refusing T&S table authority')
        if db.execute("SELECT EXISTS(SELECT FROM pg_namespace WHERE nspname=ANY(%s) AND has_schema_privilege(%s,oid,'CREATE'))", (list(SCHEMAS), role)).fetchone()[0]:
            raise RuntimeError('Refusing T&S schema authority')
    else:
        db.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
    db.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
    db.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(database), sql.Identifier(role)))
    db.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
        sql.SQL(',').join(sql.Identifier(schema) for schema in schemas), sql.Identifier(role)))
    for signature in signatures:
        # Fixed reviewed signature, never caller-supplied SQL/catalog overloads.
        db.execute(sql.SQL('GRANT EXECUTE ON FUNCTION ' + signature + ' TO {}').format(sql.Identifier(role)))
    if db.execute('SELECT 1 FROM audit.writer_principals WHERE database_role=%s', (role,)).fetchone() is None:
        chain, actor = uuid.uuid4(), uuid.uuid4()
        db.execute('INSERT INTO audit.chain_heads(chain_id) VALUES(%s)', (chain,))
        db.execute('INSERT INTO audit.writer_principals(database_role,actor_id,chain_id) VALUES(%s,%s,%s)', (role, actor, chain))


def verify(ingress, role):
    """The login sees exactly its capabilities and no table authority."""
    _, _, signatures = LOGINS[role]
    granted = ingress.execute('SELECT current_user, bool_and(has_function_privilege(s, \'EXECUTE\')) FROM unnest(%s::text[]) s',
                              (list(signatures),)).fetchone()
    if granted != (role, True):
        raise RuntimeError('T&S connection not ready')


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
                verify(ingress, role)
    except Exception:
        raise SystemExit('T&S provisioning failed; credentials and server diagnostics were not printed') from None
    print('T&S DEV database identities ready: ' + ', '.join(sorted(targets)) + '; staff accounts, broker and activation flags unchanged')
