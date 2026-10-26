SET search_path TO public;

-- Cut over atomically. Historical notifications and read timestamps stay intact.
DROP TRIGGER sesion_notificacion ON sesion;
DROP FUNCTION notificar_reserva();
ALTER TABLE sesion ADD COLUMN event_revision BIGINT NOT NULL DEFAULT 0;
CREATE TABLE booking_outbox (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sesion_id UUID NOT NULL REFERENCES sesion(id) ON DELETE CASCADE,
  revision BIGINT NOT NULL CHECK (revision > 0),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT statement_timestamp(),
  payload JSONB NOT NULL,
  published_at TIMESTAMPTZ,
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (sesion_id, revision)
);
CREATE INDEX booking_outbox_pending ON booking_outbox(next_attempt_at, occurred_at) WHERE published_at IS NULL;
CREATE INDEX booking_outbox_order ON booking_outbox(sesion_id, revision) WHERE published_at IS NULL;

CREATE FUNCTION booking_revision() RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
  IF TG_OP='INSERT' THEN NEW.event_revision := 1;
  ELSIF NEW.estado IS DISTINCT FROM OLD.estado THEN NEW.event_revision := OLD.event_revision+1;
  ELSE NEW.event_revision := OLD.event_revision;
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER booking_revision BEFORE INSERT OR UPDATE ON sesion FOR EACH ROW EXECUTE FUNCTION booking_revision();
CREATE FUNCTION enqueue_booking_event() RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
DECLARE event_id UUID := gen_random_uuid(); event_time TIMESTAMPTZ := statement_timestamp();
BEGIN
  IF TG_OP='UPDATE' THEN
    IF NEW.estado IS NOT DISTINCT FROM OLD.estado THEN RETURN NEW; END IF;
  END IF;
  INSERT INTO booking_outbox(id,sesion_id,revision,occurred_at,payload)
  VALUES(event_id,NEW.id,NEW.event_revision,event_time,jsonb_build_object(
    'schema_version',1,'event_type','booking.state_changed','event_id',event_id,
    'booking_id',NEW.id,'revision',NEW.event_revision,'occurred_at',event_time,
    'state',NEW.estado::text,'recipients',(SELECT jsonb_agg(DISTINCT u) FROM unnest(ARRAY[NEW.cliente_id,NEW.compa_id]) u)));
  RETURN NEW;
END;
$$;
CREATE TRIGGER booking_event AFTER INSERT OR UPDATE OF estado ON sesion FOR EACH ROW EXECUTE FUNCTION enqueue_booking_event();

CREATE TABLE alert_event_inbox (
  event_id UUID PRIMARY KEY,
  payload_hash BYTEA NOT NULL,
  processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE notificacion ADD COLUMN evento_id UUID;
CREATE UNIQUE INDEX notificacion_event_recipient ON notificacion(evento_id,usuario_id) WHERE evento_id IS NOT NULL;
-- Quarantine is durable, access-controlled in PostgreSQL; no message bodies in logs.
CREATE TABLE alert_event_quarantine (
  payload_hash BYTEA PRIMARY KEY,
  payload BYTEA NOT NULL CHECK (octet_length(payload)<=16384),
  reason TEXT NOT NULL CHECK (reason IN ('invalid_event','event_id_conflict')),
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
