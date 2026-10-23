"""One-shot operator bootstrap for RAC only, before the non-superuser migrator.

Uses libpq PG* operator credentials; no API receives these credentials.
Passwords use connection-aware psycopg quoting for PostgreSQL utility statements;
they never appear in logs or command arguments.
Existing application objects are transferred within this database only; extension
members and the separate Keycloak database are not reassigned.
"""
import os
import psycopg
from psycopg import sql
from database_roles import validate_credentials


def configure(values, connect=psycopg.connect):
    credentials = validate_credentials(values)
    with connect() as db:
        current, superuser = db.execute('SELECT current_database(),rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()
        if current != values['POSTGRES_DB'] or not superuser:
            raise RuntimeError('RAC database operator connection required')
        for role, password in credentials.items():
            row = db.execute('SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s', (role,)).fetchone()
            if row and any(row):
                raise RuntimeError('Refusing privileged service identity: ' + role)
            memberships = db.execute('SELECT granted.rolname FROM pg_auth_members m JOIN pg_roles granted ON granted.oid=m.roleid JOIN pg_roles member ON member.oid=m.member WHERE member.rolname=%s', (role,)).fetchall()
            if memberships:
                raise RuntimeError('Unexpected inherited privileges: ' + role)
            if not row:
                db.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
            # PostgreSQL utility statements do not accept password bind parameters.
            # psycopg Literal escapes server-side using connection encoding.
            db.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
        # V018 defines these capability groups; precreate them to avoid granting
        # CREATEROLE to the migrator. No memberships are given to application roles.
        for role in ('rac_audit_writer', 'rac_audit_reader'):
            if not db.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                db.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
        for extension in ('postgis', 'pgcrypto', 'btree_gist'):
            db.execute(sql.SQL('CREATE EXTENSION IF NOT EXISTS {}').format(sql.Identifier(extension)))
        db.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        db.execute(sql.SQL('REVOKE CONNECT,TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(current)))
        roles = sql.SQL(',').join(sql.Identifier(r) for r in credentials)
        db.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(current), roles))
        db.execute(sql.SQL('GRANT CREATE ON DATABASE {} TO rac_migrator').format(sql.Identifier(current)))
        # Ownership is required for forward ALTERs on existing DEV schemas. No
        # REASSIGN OWNED: that would also transfer cluster/shared objects.
        for schema in ('public', 'meta', 'audit', 'standing'):
            if not db.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (schema,)).fetchone():
                continue
            db.execute(sql.SQL('ALTER SCHEMA {} OWNER TO rac_migrator').format(sql.Identifier(schema)))
        relations = db.execute("""SELECT n.nspname,c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
          WHERE n.nspname IN ('public','meta','audit','standing') AND c.relkind IN ('r','p','S','v','m')
          AND NOT EXISTS(SELECT FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
          ORDER BY CASE WHEN c.relkind='S' THEN 1 ELSE 0 END""").fetchall()
        for schema, name, kind in relations:
            object_kind = {'S': 'SEQUENCE', 'v': 'VIEW', 'm': 'MATERIALIZED VIEW'}.get(kind, 'TABLE')
            db.execute(sql.SQL('ALTER ' + object_kind + ' {}.{} OWNER TO rac_migrator').format(sql.Identifier(schema), sql.Identifier(name)))
        functions = db.execute("""SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname IN ('public','meta','audit','standing') AND NOT EXISTS
          (SELECT FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')""").fetchall()
        for (signature,) in functions:
            # regprocedure comes only from this database's catalog, not a user payload.
            db.execute(sql.SQL('ALTER FUNCTION ' + signature + ' OWNER TO rac_migrator'))
        types = db.execute("""SELECT n.nspname,t.typname,t.typtype FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
          WHERE n.nspname IN ('public','meta','audit','standing') AND t.typtype IN ('e','d') AND NOT EXISTS
          (SELECT FROM pg_depend d WHERE d.classid='pg_type'::regclass AND d.objid=t.oid AND d.deptype='e')""").fetchall()
        for schema, name, kind in types:
            db.execute(sql.SQL('ALTER ' + ('DOMAIN' if kind == 'd' else 'TYPE') + ' {}.{} OWNER TO rac_migrator').format(sql.Identifier(schema), sql.Identifier(name)))
        db.execute('GRANT CONNECT ON DATABASE keycloak TO rac_backup')
        # PostGIS may install extension schemas (tiger/topology). pg_dump includes
        # their configuration data too; grant reads only in this RAC database,
        # never a cluster-wide catalog-reading role.
        for (schema,) in db.execute("SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname<>'information_schema'").fetchall():
            db.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO rac_backup').format(sql.Identifier(schema)))
            db.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA {} TO rac_backup').format(sql.Identifier(schema)))
            db.execute(sql.SQL('GRANT SELECT ON ALL SEQUENCES IN SCHEMA {} TO rac_backup').format(sql.Identifier(schema)))
    with connect(dbname='keycloak') as identity_db:
        identity_db.execute('CREATE SCHEMA IF NOT EXISTS kc AUTHORIZATION keycloak')
        identity_db.execute('GRANT USAGE ON SCHEMA kc TO rac_backup')
        identity_db.execute('GRANT SELECT ON ALL TABLES IN SCHEMA kc TO rac_backup')
        identity_db.execute('GRANT SELECT ON ALL SEQUENCES IN SCHEMA kc TO rac_backup')
        identity_db.execute('ALTER DEFAULT PRIVILEGES FOR ROLE keycloak IN SCHEMA kc GRANT SELECT ON TABLES TO rac_backup')
        identity_db.execute('ALTER DEFAULT PRIVILEGES FOR ROLE keycloak IN SCHEMA kc GRANT SELECT ON SEQUENCES TO rac_backup')


if __name__ == '__main__':
    try:
        configure(os.environ)
    except Exception:
        # No server diagnostic or parameter dump: failures are investigated by
        # the operator against the disposable reproduction/controlled DB console.
        raise SystemExit('Database role configuration failed; credentials were not printed.') from None
    print('Dedicated database roles configured; credentials were not printed.')
