"""Synthetic seed for isolated document writer databases, never DEV."""
BUYER = '11111111-1111-4111-8111-000000000101'
COMPA = '11111111-1111-4111-8111-000000000102'
BOOKING = '11111111-1111-4111-8111-000000000201'

def seed(execute, active=False):
    execute("INSERT INTO audit.chain_heads(chain_id) VALUES('11111111-1111-4111-8111-111111111111'); INSERT INTO audit.writer_principals VALUES('postgres','22222222-2222-4222-8222-222222222222','11111111-1111-4111-8111-111111111111');")
    execute("INSERT INTO legal_documents(kind,version,locale,content,material_change,legal_review,approved_by,reviewed_at,published_at) SELECT kind,'writer-1','es','Synthetic document writer fixture',true,'approved',gen_random_uuid(),now()-interval '2 days',now()-interval '1 day' FROM unnest(ARRAY['terms_client','terms_compa','community_rules','privacy','safety_rules']) kind;")
    execute("SELECT documents.activate(gen_random_uuid(),0,'es',ARRAY(SELECT id FROM legal_documents ORDER BY kind),gen_random_uuid(),gen_random_uuid());")
    for ident, role in ((BUYER, 'cliente'), (COMPA, 'compa')):
        execute(f"INSERT INTO usuario(id,nombre,correo,rol,keycloak_id) VALUES('{ident}','Synthetic','{ident}@writer.test','{role}','{ident}');")
    execute(f"INSERT INTO compa_perfil(id,usuario_id,descripcion,tarifa_hora) VALUES(gen_random_uuid(),'{COMPA}','Synthetic companion fixture',10000);")
    import json
    availability = json.dumps({day: ["00:00-23:59"] for day in ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")})
    execute(f"INSERT INTO compa_availability(compa_id,disponibilidad_json,zona_horaria) VALUES('{COMPA}','{availability}','UTC');")
    state = 'activa' if active else 'pendiente'
    execute(f"INSERT INTO sesion(id,cliente_id,compa_id,fecha_inicio,fecha_fin,estado,monto_total) VALUES('{BOOKING}','{BUYER}','{COMPA}',date_trunc('day',now())+interval '3 days 12 hours',date_trunc('day',now())+interval '3 days 13 hours','{state}',10000);")
