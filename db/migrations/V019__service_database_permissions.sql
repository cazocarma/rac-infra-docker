SET search_path=public;
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['rac_user','rac_match','rac_chat','rac_alert','rac_maintenance','rac_relay','rac_alert_consumer','rac_seed','rac_backup'] LOOP
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN EXECUTE format('CREATE ROLE %I NOLOGIN',r); END IF;
 END LOOP;
END $$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;
-- Application-owned functions, not PostGIS/extension functions.
DO $$ DECLARE f record; BEGIN
 FOR f IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname='public' AND NOT EXISTS(SELECT FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',f.signature);
 END LOOP;
END $$;

-- Locks are a restricted operation, not a grant to mutate another owner's data.
CREATE FUNCTION lock_booking(p_id uuid,p_subject text,p_exclusive boolean DEFAULT false) RETURNS SETOF sesion
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF p_exclusive THEN RETURN QUERY SELECT s.* FROM public.sesion s JOIN public.usuario u ON u.id IN(s.cliente_id,s.compa_id)
  WHERE s.id=p_id AND u.keycloak_id=p_subject FOR UPDATE OF s;
 ELSE RETURN QUERY SELECT s.* FROM public.sesion s JOIN public.usuario u ON u.id IN(s.cliente_id,s.compa_id)
  WHERE s.id=p_id AND u.keycloak_id=p_subject FOR SHARE OF s; END IF;
END $$;
REVOKE ALL ON FUNCTION lock_booking(uuid,text,boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lock_booking(uuid,text,boolean) TO rac_user,rac_chat;

-- Trigger-only operations keep the same checks, but don't require application
-- privileges on another owner's tables or direct outbox writes.
ALTER FUNCTION validar_resena_verificada() SECURITY DEFINER;
ALTER FUNCTION validar_resena_verificada() SET search_path=pg_catalog,public;
ALTER FUNCTION validar_mensaje_reserva() SECURITY DEFINER;
ALTER FUNCTION validar_mensaje_reserva() SET search_path=pg_catalog,public;
ALTER FUNCTION encolar_mensaje_chat() SECURITY DEFINER;
ALTER FUNCTION encolar_mensaje_chat() SET search_path=pg_catalog,public;
ALTER FUNCTION enqueue_booking_event() SECURITY DEFINER;
ALTER FUNCTION enqueue_booking_event() SET search_path=pg_catalog,public;
ALTER FUNCTION guard_booking_time_off() SECURITY DEFINER;
ALTER FUNCTION guard_booking_time_off() SET search_path=pg_catalog,public;

GRANT USAGE ON SCHEMA public TO rac_user,rac_match,rac_chat,rac_alert,rac_maintenance,rac_relay,rac_alert_consumer,rac_seed;
GRANT SELECT,INSERT,UPDATE ON usuario,compa_perfil,skill,compa_perfil_skill TO rac_user;
GRANT SELECT,INSERT ON reserva_resena TO rac_user;
GRANT SELECT,INSERT ON compa_availability TO rac_user;
GRANT UPDATE(disponibilidad_json,zona_horaria,actualizado_en) ON compa_availability TO rac_user;
GRANT SELECT ON sesion TO rac_user;
GRANT EXECUTE ON FUNCTION refresh_habilidades_cache(uuid) TO rac_user;

GRANT SELECT,INSERT,UPDATE ON sesion,compa_availability,sesion_cupo_semanal TO rac_match;
GRANT SELECT,INSERT,UPDATE,DELETE ON compa_time_off TO rac_match;
GRANT SELECT ON compa_suscripcion TO rac_match;
GRANT SELECT(id,keycloak_id) ON usuario TO rac_match;
GRANT SELECT(id,usuario_id) ON compa_perfil TO rac_match;

GRANT SELECT ON sesion,chat_cursor,chat_outbox TO rac_chat;
GRANT SELECT(id,keycloak_id,nombre) ON usuario TO rac_chat;
GRANT SELECT,INSERT ON mensaje,chat_auditoria TO rac_chat;
GRANT SELECT,INSERT,DELETE ON chat_bloqueo TO rac_chat;
GRANT SELECT,INSERT ON chat_reporte TO rac_chat;
GRANT UPDATE(estado) ON chat_reporte TO rac_chat;
GRANT USAGE ON SEQUENCE mensaje_numero_seq,chat_auditoria_id_seq TO rac_chat;

GRANT SELECT ON notificacion TO rac_alert;
GRANT UPDATE(leido_en) ON notificacion TO rac_alert;
GRANT SELECT(id,keycloak_id) ON usuario TO rac_alert;
GRANT SELECT ON sesion TO rac_maintenance;
GRANT UPDATE(estado,actualizado_en) ON sesion TO rac_maintenance;
GRANT SELECT ON booking_outbox TO rac_relay;
GRANT UPDATE(attempts,next_attempt_at,published_at) ON booking_outbox TO rac_relay;
GRANT SELECT,INSERT ON alert_event_inbox TO rac_alert_consumer;
GRANT INSERT ON alert_event_quarantine,notificacion TO rac_alert_consumer;
GRANT SELECT(id) ON usuario TO rac_alert_consumer;
GRANT SELECT(id,cliente_id,compa_id) ON sesion TO rac_alert_consumer;

-- DEV seeding is a separate operator tool, never an API credential.
GRANT SELECT,INSERT,UPDATE ON usuario,compa_perfil,skill TO rac_seed;
GRANT SELECT,INSERT ON compa_availability TO rac_seed;
-- Explicit backup reads, not pg_read_all_data (which would expose catalogs
-- beyond the two intended databases). Future migrator-owned tables inherit read.
GRANT USAGE ON SCHEMA public,meta,audit TO rac_backup;
DO $$ DECLARE s text; BEGIN
 FOREACH s IN ARRAY ARRAY['public','meta','audit'] LOOP
  EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO rac_backup',s);
  EXECUTE format('GRANT SELECT ON ALL SEQUENCES IN SCHEMA %I TO rac_backup',s);
  EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES TO rac_backup',s);
  EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON SEQUENCES TO rac_backup',s);
 END LOOP;
END $$;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
