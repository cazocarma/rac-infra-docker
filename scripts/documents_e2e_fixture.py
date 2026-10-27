"""Reviewed-looking SYNTHETIC material exclusively for the disposable P04 lab."""
import json
import os
import re
import uuid
import psycopg

if (os.environ.get('RAC_ENV') != 'dev' or os.environ.get('PGHOST') != 'postgres' or
        os.environ.get('PGDATABASE') != 'rac_documents_e2e' or
        not re.fullmatch(r'rac-documents-e2e-[0-9a-f]{12}', os.environ.get('RAC_DISPOSABLE_PROJECT', ''))):
    raise RuntimeError('Disposable document lab required')

with psycopg.connect() as db:
    if db.execute("SELECT version FROM documents.head WHERE locale='es'").fetchone()[0] != 0:
        raise RuntimeError('Document fixture already initialized')
    chain, actor = uuid.uuid4(), uuid.uuid4()
    db.execute('INSERT INTO audit.chain_heads(chain_id) VALUES(%s)', (chain,))
    db.execute('INSERT INTO audit.writer_principals VALUES(%s,%s,%s)', ('postgres', actor, chain))
    ids = []
    for kind in ('terms_client', 'terms_compa', 'community_rules', 'privacy', 'safety_rules'):
        content = ('DOCUMENTO SINTÉTICO PARA PRUEBAS. No son términos legales definitivos.\n'
                   'Esta versión permite comprobar la lectura, la selección explícita y el historial.\n'
                   'No se publica contenido real ni se habilitan pagos. Tipo: ' + kind)
        ident = db.execute("""INSERT INTO legal_documents(kind,version,locale,content,material_change,legal_review,approved_by,reviewed_at,published_at)
 VALUES(%s,'browser-synthetic-1','es',%s,true,'approved',%s,now()-interval '2 hours',now()-interval '1 hour') RETURNING id""", (kind, content, actor)).fetchone()[0]
        ids.append(ident)
    db.execute("SELECT documents.activate(%s,0,'es',%s,%s,%s,%s)",
        (uuid.uuid4(), ids, uuid.uuid4(), actor, ['Material sintético de prueba.', 'Aceptación explícita por versión.', 'Historial propio sin publicación real.']))
    statements = [
        ('no_illicit_substances', 'No ofreceré, compraré, venderé, entregaré ni coordinaré drogas u otras sustancias ilícitas, ni en RAC ni en encuentros reservados por RAC.'),
        ('no_sexual_services', 'No ofreceré servicios ni contenido sexual.'),
        ('catalog_only', 'Solo ofreceré actividades del catálogo de RAC.'),
        ('adults_only', 'No aceptaré reservas que involucren a menores de edad.'),
        ('enforcement_and_appeal', 'Entiendo que RAC puede retirar mi publicación y suspender mi cuenta si incumplo estas reglas, y que puedo apelar.'),
    ]
    questions = [
        ('substances', 'Una persona pide que lleves sustancias ilícitas. ¿Qué haces?'),
        ('underage', 'Una reserva involucra a una persona menor de edad. ¿Qué haces?'),
        ('outside_catalog', 'Te piden una actividad prohibida fuera del catálogo. ¿Qué haces?'),
    ]
    # Key order matches the Go Content/Question struct serialization exactly.
    content = {'statements': [{'id': key, 'text': text} for key, text in statements],
        'questions': [{'id': key, 'text': text,
            'options': [{'id': 'reject_report', 'text': 'Lo rechazo y lo reporto'},
                        {'id': 'proceed', 'text': 'Continúo de todas formas'}],
            'correct_option': 'reject_report'} for key, text in questions]}
    raw = json.dumps(content, ensure_ascii=False, separators=(',', ':'))
    definition = db.execute("""INSERT INTO compa_attestation_versions(version,locale,content,legal_review,approved_by,reviewed_at,published_at)
 VALUES('browser-synthetic-1','es',%s,'approved',%s,now()-interval '2 hours',now()-interval '1 hour') RETURNING id""", (raw, actor)).fetchone()[0]
    db.execute("INSERT INTO compa_attestation_requirements(locale,registry_version,definition_id) VALUES('es',1,%s)", (definition,))
print('PASS: synthetic reviewed document/quiz fixture seeded in disposable lab only')
