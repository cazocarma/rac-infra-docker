SET search_path TO public;
CREATE INDEX sesion_pending_expiry ON sesion(fecha_inicio,id) WHERE estado='pendiente';
CREATE FUNCTION guard_late_acceptance() RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
 IF OLD.estado='pendiente' AND NEW.estado='activa' AND NEW.fecha_inicio<=clock_timestamp() THEN
  RAISE EXCEPTION 'booking_expired' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_late_acceptance BEFORE UPDATE OF estado ON sesion FOR EACH ROW EXECUTE FUNCTION guard_late_acceptance();
-- Existing states retain their v1 event; the new state uses the v2 contract.
CREATE OR REPLACE FUNCTION enqueue_booking_event() RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
DECLARE event_id UUID := gen_random_uuid(); event_time TIMESTAMPTZ := statement_timestamp();
BEGIN
 IF TG_OP='UPDATE' THEN IF NEW.estado IS NOT DISTINCT FROM OLD.estado THEN RETURN NEW; END IF; END IF;
 INSERT INTO booking_outbox(id,sesion_id,revision,occurred_at,payload)
 VALUES(event_id,NEW.id,NEW.event_revision,event_time,jsonb_build_object(
 'schema_version',CASE WHEN NEW.estado='expirada' THEN 2 ELSE 1 END,'event_type','booking.state_changed','event_id',event_id,
 'booking_id',NEW.id,'revision',NEW.event_revision,'occurred_at',event_time,'state',NEW.estado::text,
 'recipients',(SELECT jsonb_agg(DISTINCT u) FROM unnest(ARRAY[NEW.cliente_id,NEW.compa_id]) u)));
 RETURN NEW;
END $$;
