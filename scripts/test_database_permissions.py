"""Disposable fresh + V018 upgrade with real non-superuser Flyway, role
bootstrap and negative permissions. Never reads .env or uses the DEV cluster.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
from database_roles import ROLES

ROOT = Path(__file__).resolve().parents[1]


def run(*args, input=None, ok=True):
    result = subprocess.run(args, input=input, capture_output=True, text=True, timeout=300)
    if ok and result.returncode:
        raise RuntimeError('Disposable database test command failed: ' + args[0] + '\n' + result.stderr[-1500:])
    return result


def main():
    name = 'rac-permissions-test-' + uuid.uuid4().hex[:12]
    tools = name + '-tools'

    def sql(database, statement, role='postgres', ok=True):
        return run('docker', 'exec', '-i', name, 'psql', '-X', '-v', 'ON_ERROR_STOP=1', '-U', role, '-d', database, '-Atq', input=statement, ok=ok)

    def migrate(database, directory, role='rac_migrator'):
        run('docker', 'run', '--rm', '--network', name,
            '--mount', f'type=bind,source={directory},target=/flyway/sql,readonly',
            '-e', f'FLYWAY_URL=jdbc:postgresql://postgres:5432/{database}',
            '-e', 'FLYWAY_USER=' + role, '-e', 'FLYWAY_PASSWORD=' + (password if role == 'rac_migrator' else 'test-only'),
            '-e', 'FLYWAY_SCHEMAS=meta', '-e', 'FLYWAY_DEFAULT_SCHEMA=meta', '-e', 'FLYWAY_TABLE=schema_history',
            'flyway/flyway:11.15.0-alpine', 'migrate')

    password = 'synthetic-migration-password-123456'

    def bootstrap(database):
        environment = {'PGHOST': 'postgres', 'PGUSER': 'postgres', 'PGPASSWORD': 'test-only', 'PGDATABASE': database,
            'POSTGRES_DB': database, 'MIGRATION_DB_USER': 'rac_migrator', 'MIGRATION_DB_PASSWORD': password}
        for key, role in ROLES.items():
            environment[key] = f'postgresql://{role}:synthetic-independent-{role}-123456@postgres:5432/{database}?sslmode=disable'
        flags = [arg for key, value in environment.items() for arg in ('-e', key + '=' + value)]
        run('docker', 'run', '--rm', '--network', name, *flags, tools, 'python', 'configure_database.py')

    try:
        run('docker', 'network', 'create', name)
        run('docker', 'run', '-d', '--name', name, '--network', name, '--network-alias', 'postgres',
            '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_PASSWORD=test-only', '-e', 'POSTGRES_DB=fresh', 'postgis/postgis:16-3.4')
        for _ in range(60):
            if sql('fresh', 'SELECT 1;', ok=False).returncode == 0 and 'PostgreSQL init process complete' in run('docker','logs',name).stdout:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Disposable database not ready')
        sql('fresh', 'CREATE ROLE keycloak LOGIN; CREATE DATABASE keycloak OWNER keycloak; CREATE DATABASE upgrade;')
        run('docker', 'build', '-q', '-t', tools, '-f', str(ROOT / 'tools/Dockerfile'), str(ROOT))
        with tempfile.TemporaryDirectory(prefix=name) as directory:
            for source in (ROOT / 'db/migrations').glob('V*.sql'):
                if int(source.name.split('__')[0][1:]) <= 18:
                    shutil.copy2(source, Path(directory) / source.name)
            migrate('upgrade', directory, 'postgres')
        # Both pre-existing and brand-new schemas run through the actual operator
        # bootstrap, then the exact same migration identity without superuser.
        for database in ('fresh', 'upgrade'):
            bootstrap(database)
            bootstrap(database)
            migrate(database, ROOT / 'db/migrations')
            bootstrap(database)  # Reconcile again with the standing schema present.
            editorial_flags = [
                '-e', 'RAC_ENV=dev', '-e', 'PGHOST=postgres', '-e', 'PGUSER=postgres',
                '-e', 'PGPASSWORD=test-only', '-e', 'PGDATABASE=' + database,
                '-e', 'POSTGRES_DB=' + database,
                '-e', 'DOCUMENT_EDITORIAL_DATABASE_URL=postgresql://rac_documents_editorial:synthetic-editorial-password-123456@postgres:5432/' + database + '?sslmode=disable',
            ]
            for _ in range(2):
                run('docker', 'run', '--rm', '--network', name, *editorial_flags, tools, 'python', 'editorial_database.py')
            identity = sql(database, "SELECT actor_id::text||':'||chain_id::text FROM audit.writer_principals WHERE database_role='rac_documents_editorial';").stdout.strip()
            sql(database, 'GRANT SELECT(content) ON legal_documents TO rac_documents_editorial;')
            refused = run('docker', 'run', '--rm', '--network', name, *editorial_flags, tools, 'python', 'editorial_database.py', ok=False)
            assert refused.returncode != 0, 'Provisioning accepted unexpected column authority'
            assert 'synthetic-editorial-password' not in refused.stdout + refused.stderr
            sql(database, 'REVOKE SELECT(content) ON legal_documents FROM rac_documents_editorial;')
            run('docker', 'run', '--rm', '--network', name, *editorial_flags, tools, 'python', 'editorial_database.py')
            assert sql(database, "SELECT actor_id::text||':'||chain_id::text FROM audit.writer_principals WHERE database_role='rac_documents_editorial';").stdout.strip() == identity
            assert sql(database, 'SELECT documents.editorial_ready();', 'rac_documents_editorial').stdout.strip() == 't'
            assert sql(database, "SELECT count(*) FROM audit.writer_principals WHERE database_role='rac_documents_editorial';").stdout.strip() == '1'
            for forbidden in ('SELECT * FROM legal_documents;', 'SELECT content FROM legal_documents;',
                              'UPDATE notificacion SET titulo=titulo;',
                              "SELECT documents.editorial_record(gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),gen_random_uuid(),'document.drafted','{}');"):
                assert sql(database, forbidden, 'rac_documents_editorial', ok=False).returncode != 0
            assert sql(database, "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='standing';").stdout.strip() == 'rac_migrator'
            if (ROOT / 'db/migrations/V029__document_registry.sql').exists():
                from document_registry_checks import check as check_document_registry
                assert sql(database, "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='documents';").stdout.strip() == 'rac_migrator'
                check_document_registry(lambda statement: sql(database, statement).stdout.strip(),
                                        lambda statement: sql(database, statement, ok=False).returncode != 0,
                                        role='registry_fixture_' + database)
                if (ROOT / 'db/migrations/V030__document_commit_fence.sql').exists():
                    assert sql(database, "BEGIN; SET ROLE rac_user; SELECT documents.lock_head('es'); ROLLBACK;").returncode == 0
                    for denied_role in ('rac_match', 'rac_chat', 'rac_alert', 'rac_backup'):
                        assert sql(database, "SELECT documents.lock_head('es');", denied_role, ok=False).returncode != 0
                    assert sql(database, "SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='documents.lock_head(text)'::regprocedure;").stdout.strip() == 'rac_migrator'
                if (ROOT / 'db/migrations/V031__document_reader_commit_fence.sql').exists():
                    for reader_role in ('rac_user', 'rac_match', 'rac_chat'):
                        assert sql(database, "BEGIN; SELECT * FROM documents.lock_registry('es'); ROLLBACK;", reader_role).returncode == 0
                    for reader_role in ('rac_match', 'rac_chat'):
                        for private_table in ('public.legal_documents', 'public.document_acceptances', 'documents.registry'):
                            assert sql(database, 'SELECT * FROM ' + private_table + ';', reader_role, ok=False).returncode != 0
                    for denied_role in ('rac_alert', 'rac_backup'):
                        assert sql(database, "SELECT * FROM documents.lock_registry('es');", denied_role, ok=False).returncode != 0
                    assert sql(database, "SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid='documents.lock_registry(text)'::regprocedure;").stdout.strip() == 'rac_migrator'



            assert sql(database, "SELECT count(*) FROM standing.account;", 'rac_user').returncode == 0
            assert sql(database, "UPDATE standing.account SET status='active';", 'rac_user', ok=False).returncode != 0
            assert sql(database, "SELECT count(*) FROM standing.account;", 'rac_match', ok=False).returncode != 0
            assert sql(database, "SELECT count(*) FROM match_standing_inbox;", 'rac_match').returncode == 0
            assert sql(database, "SELECT count(*) FROM match_standing_effect;", 'rac_user', ok=False).returncode != 0
            assert sql(database, "SELECT count(*) FROM public.match_standing_quarantine;", 'rac_standing_match').returncode == 0
            assert sql(database, "SELECT to_regclass('meta.match_standing_quarantine') IS NULL;").stdout.strip() == 't'
            assert sql(database, "SELECT status FROM standing.account;", 'rac_standing_relay', ok=False).returncode != 0
            assert sql(database, "SELECT correo FROM usuario;", 'rac_standing_match', ok=False).returncode != 0
            assert sql(database, "SELECT count(*) FROM match_booking_standing;", 'rac_standing_match').returncode == 0
            assert sql(database, "UPDATE match_booking_standing SET client_version=999;", 'rac_standing_match', ok=False).returncode != 0
            assert sql(database, "SELECT count(*) FROM match_booking_standing;", 'rac_user', ok=False).returncode != 0
            assert sql(database, "SELECT event_id,subject_id,standing_version,payload FROM standing.outbox;", 'rac_user').returncode == 0
            assert sql(database, "SELECT command FROM standing.outbox;", 'rac_user', ok=False).returncode != 0
            assert sql(database, "SELECT payload FROM standing.outbox;", 'rac_standing_match', ok=False).returncode != 0
            assert sql(database, "UPDATE match_standing_projection SET status=status;", 'rac_match', ok=False).returncode != 0
            assert sql(database, "UPDATE match_standing_sync SET version=version;", 'rac_match', ok=False).returncode != 0
            assert sql(database, "SELECT count(*) FROM match_standing_sanction;", 'rac_user', ok=False).returncode != 0

            assert sql(database, "SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls FROM pg_roles WHERE rolname='rac_migrator';").stdout.strip() == 'f'
            for role in ROLES.values():
                assert sql(database, 'CREATE TABLE public.unauthorized(id int);', role, ok=False).returncode != 0
                assert sql(database, 'CREATE SCHEMA unauthorized;', role, ok=False).returncode != 0
                assert sql(database, 'CREATE TEMP TABLE unauthorized(id int);', role, ok=False).returncode != 0
            for role, forbidden in [
                ('rac_user', 'UPDATE sesion SET estado=estado;'),
                ('rac_chat', 'UPDATE sesion SET estado=estado;'),
                ('rac_match', 'SELECT contenido FROM mensaje;'),
                ('rac_relay', 'SELECT correo FROM usuario;'),
                ('rac_alert', 'INSERT INTO notificacion(usuario_id,sesion_id,tipo,titulo) VALUES(NULL,NULL,\'x\',\'x\');'),
                ('rac_alert_consumer', 'UPDATE usuario SET nombre=nombre;'),
                ('rac_standing_alert', 'UPDATE notificacion SET template_version=template_version;'),
                ('rac_alert', 'UPDATE notificacion SET template_key=template_key;'),
                ('rac_chat', 'SELECT telefono,correo FROM usuario;'),
                ('rac_seed', 'SELECT contenido FROM mensaje;'),
            ]:
                assert sql(database, forbidden, role, ok=False).returncode != 0, (role, forbidden)
            assert sql(database, 'SELECT count(*) FROM meta.schema_history;', 'rac_user', ok=False).returncode != 0
            assert sql(database, 'SELECT count(*) FROM audit.log;', 'rac_match', ok=False).returncode != 0
            # Exercise trigger paths as the actual role, including the locks that
            # previously required granting UPDATE on another owner's table.
            client, compa, booking = [str(uuid.uuid4()) for _ in range(3)]
            sql(database, f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES('{client}','Fixture','client@example.test','cliente','kc-c'),('{compa}','Fixture','compa@example.test','compa','kc-p');", 'rac_user')
            # Replacing skills requires DELETE even when the profile is new and
            # the association table has no matching rows. Other owners retain
            # no delete permission on user-owned associations.
            sql(database, 'DELETE FROM compa_perfil_skill WHERE false;', 'rac_user')
            for other in ('rac_match', 'rac_chat', 'rac_alert'):
                assert sql(database, 'DELETE FROM compa_perfil_skill WHERE false;', other, ok=False).returncode != 0
            for _ in range(2):
                sql(database, f"INSERT INTO compa_availability(compa_id,disponibilidad_json,zona_horaria) VALUES('{compa}','{{}}','UTC') ON CONFLICT(compa_id) DO UPDATE SET disponibilidad_json=EXCLUDED.disponibilidad_json,zona_horaria=EXCLUDED.zona_horaria,actualizado_en=now();", 'rac_user')
            sql(database, f"INSERT INTO sesion(id,cliente_id,compa_id,fecha_inicio,fecha_fin,estado) VALUES('{booking}','{client}','{compa}',now()+interval '1 day',now()+interval '25 hours','activa');", 'rac_match')
            assert sql(database, f"SELECT count(*) FROM lock_booking('{booking}','foreign-subject',true);", 'rac_chat').stdout.strip()=='0'
            sql(database, f"BEGIN; SELECT id FROM lock_booking('{booking}','kc-c',true); INSERT INTO mensaje(sesion_id,remitente_id,contenido) VALUES('{booking}','{client}','synthetic fixture'); COMMIT;", 'rac_chat')
            assert sql(database, 'SELECT count(*) FROM booking_outbox;', 'rac_relay').stdout.strip() == '1'
            assert sql(database, 'SELECT count(*) FROM chat_outbox;', 'rac_chat').stdout.strip() == '1'
            sql(database, f"UPDATE sesion SET fecha_inicio=now()-interval '2 hours',fecha_fin=now()-interval '1 hour',estado='finalizada' WHERE id='{booking}';", 'rac_match')
            sql(database, f"BEGIN; SELECT id FROM lock_booking('{booking}','kc-c',false); INSERT INTO reserva_resena VALUES('{booking}','{client}','{compa}',5,'fixture',now()); COMMIT;", 'rac_user')
            event=str(uuid.uuid4())
            sql(database, f"INSERT INTO alert_event_inbox(event_id,payload_hash) VALUES('{event}',decode('00','hex')) ON CONFLICT DO NOTHING;", 'rac_alert_consumer')
            sql(database, f"INSERT INTO notificacion(usuario_id,sesion_id,tipo,titulo,evento_id) SELECT DISTINCT u.id,s.id,'finalizada','Fixture','{event}'::uuid FROM sesion s JOIN usuario u ON u.id IN(s.cliente_id,s.compa_id) WHERE s.id='{booking}';", 'rac_alert_consumer')
            sql(database, "UPDATE notificacion SET leido_en=now();", 'rac_alert')
            # Backup identity can dump data and role definitions, but not password
            # hashes or modifications. No superuser login is mounted in backups.
            run('docker', 'exec', name, 'pg_dump', '-U', 'rac_backup', '-d', database, '--format=custom', '--file=/tmp/disposable.dump')
            globals_dump = run('docker', 'exec', '-e', 'PGDATABASE=' + database, name, 'pg_dumpall', '-U', 'rac_backup', '--globals-only', '--no-role-passwords').stdout
            assert 'SCRAM-SHA-256$' not in globals_dump and 'PASSWORD' not in globals_dump
            assert sql(database, 'UPDATE usuario SET nombre=nombre;', 'rac_backup', ok=False).returncode != 0
            assert sql(database, 'SELECT rolpassword FROM pg_authid;', 'rac_backup', ok=False).returncode != 0
            restored = 'restored_' + database
            sql(database, 'CREATE DATABASE ' + restored + ';')
            run('docker', 'exec', name, 'pg_restore', '-U', 'postgres', '-d', restored, '--exit-on-error', '/tmp/disposable.dump')
            assert sql(restored, "SELECT has_table_privilege('rac_chat','sesion','UPDATE');").stdout.strip() == 'f'
            assert sql(restored, "SELECT has_table_privilege('rac_chat','mensaje','INSERT');").stdout.strip() == 't'
            assert sql(restored, 'SELECT count(*) FROM reserva_resena;', 'rac_user').stdout.strip() == '1'
        print('PASS: fresh and V018 upgrade, non-superuser migration, independent roles, negative permissions, trigger locks/outboxes/review and password-free backup dump')
    finally:
        run('docker', 'rm', '-f', name, ok=False)
        run('docker', 'network', 'rm', name, ok=False)
        run('docker', 'image', 'rm', tools, ok=False)


if __name__ == '__main__':
    main()
