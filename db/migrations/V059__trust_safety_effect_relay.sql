-- Delivery bookkeeping is separate from immutable T&S commands and decisions.
-- Only a function-only relay login may claim/confirm/retry. Broker I/O belongs
-- to the caller's bounded transaction; xid fencing forbids a later transaction
-- from confirming an abandoned claim. No relay or broker account is activated.
SET LOCAL lock_timeout='2s';

CREATE TABLE ts.effect_delivery_state (
 event_id uuid PRIMARY KEY REFERENCES ts.outbox(event_id),
 attempts int NOT NULL DEFAULT 0 CHECK(attempts>=0),
 next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(next_attempt_at)),
 claim_token uuid UNIQUE,
 claim_xid xid8,
 confirmed_at timestamptz CHECK(confirmed_at IS NULL OR isfinite(confirmed_at)),
 CHECK((claim_token IS NULL)=(claim_xid IS NULL)),
 CHECK(confirmed_at IS NULL OR claim_token IS NOT NULL)
);
CREATE INDEX effect_delivery_pending ON ts.effect_delivery_state(next_attempt_at,event_id) WHERE confirmed_at IS NULL;
CREATE INDEX effect_outbox_subject_order ON ts.outbox((payload->>'subject'),id);
INSERT INTO ts.effect_delivery_state(event_id) SELECT event_id FROM ts.outbox;

CREATE FUNCTION ts.create_effect_delivery_state() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN
 INSERT INTO ts.effect_delivery_state(event_id) VALUES(NEW.event_id);
 RETURN NEW;
END $$;
CREATE TRIGGER effect_delivery_created AFTER INSERT ON ts.outbox
 FOR EACH ROW EXECUTE FUNCTION ts.create_effect_delivery_state();

CREATE FUNCTION ts.preserve_effect_command() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN
 RAISE EXCEPTION 'ts_effect_command_immutable' USING ERRCODE='55000';
END $$;
CREATE TRIGGER effect_command_immutable BEFORE UPDATE OR DELETE ON ts.outbox
 FOR EACH ROW EXECUTE FUNCTION ts.preserve_effect_command();
CREATE FUNCTION ts.preserve_effect_delivery() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN
 IF TG_OP='UPDATE' THEN
  IF NEW.event_id=OLD.event_id AND OLD.confirmed_at IS NULL AND NEW.attempts>=OLD.attempts THEN
   RETURN NEW;
  END IF;
 END IF;
 RAISE EXCEPTION 'ts_effect_delivery_immutable' USING ERRCODE='55000';
END $$;
CREATE TRIGGER effect_delivery_guard BEFORE UPDATE OR DELETE ON ts.effect_delivery_state
 FOR EACH ROW EXECUTE FUNCTION ts.preserve_effect_delivery();

CREATE FUNCTION ts.effect_relay_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT FROM meta.schema_history WHERE success AND version IN('59','059'))
$$;

CREATE FUNCTION ts.claim_effect(p_claim audit.reference) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE selected ts.outbox%ROWTYPE;
BEGIN
 IF p_claim IS NULL THEN RAISE EXCEPTION 'invalid_effect_claim' USING ERRCODE='22023'; END IF;
 IF NOT ts.effect_relay_ready() THEN RAISE EXCEPTION 'effect_relay_not_ready' USING ERRCODE='42501'; END IF;
 SELECT o.* INTO selected FROM ts.outbox o JOIN ts.effect_delivery_state d ON d.event_id=o.event_id
 WHERE d.confirmed_at IS NULL AND d.next_attempt_at<=clock_timestamp()
 AND NOT EXISTS(SELECT FROM ts.outbox earlier JOIN ts.effect_delivery_state pending ON pending.event_id=earlier.event_id
  WHERE earlier.payload->>'subject'=o.payload->>'subject' AND earlier.id<o.id AND pending.confirmed_at IS NULL)
 ORDER BY o.id FOR UPDATE OF d SKIP LOCKED LIMIT 1;
 IF NOT FOUND THEN RETURN NULL; END IF;
 UPDATE ts.effect_delivery_state SET claim_token=p_claim,claim_xid=pg_current_xact_id(),
  attempts=CASE WHEN attempts<2147483647 THEN attempts+1 ELSE attempts END WHERE event_id=selected.event_id;
 RETURN jsonb_build_object('event_id',selected.event_id,'event_type',selected.event_type,
  'payload',selected.payload,'claim_token',p_claim);
END $$;

CREATE FUNCTION ts.confirm_effect(p_claim audit.reference) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE delivery ts.effect_delivery_state%ROWTYPE;
BEGIN
 IF p_claim IS NULL THEN RAISE EXCEPTION 'invalid_effect_claim' USING ERRCODE='22023'; END IF;
 SELECT * INTO delivery FROM ts.effect_delivery_state WHERE claim_token=p_claim AND claim_xid=pg_current_xact_id() FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 IF delivery.confirmed_at IS NOT NULL THEN RETURN true; END IF;
 UPDATE ts.effect_delivery_state SET confirmed_at=clock_timestamp() WHERE event_id=delivery.event_id;
 RETURN true;
END $$;

CREATE FUNCTION ts.retry_effect(p_claim audit.reference) RETURNS boolean
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE delivery ts.effect_delivery_state%ROWTYPE;
BEGIN
 IF p_claim IS NULL THEN RAISE EXCEPTION 'invalid_effect_claim' USING ERRCODE='22023'; END IF;
 SELECT * INTO delivery FROM ts.effect_delivery_state WHERE claim_token=p_claim AND claim_xid=pg_current_xact_id()
  AND confirmed_at IS NULL FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 UPDATE ts.effect_delivery_state SET claim_token=NULL,claim_xid=NULL,
  next_attempt_at=clock_timestamp()+make_interval(secs=>power(2,least(greatest(delivery.attempts-1,0),6)))
 WHERE event_id=delivery.event_id;
 RETURN true;
END $$;

CREATE FUNCTION ts.effect_relay_backlog() RETURNS jsonb
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('pending',count(*)::text,'oldest_seconds',
  greatest(COALESCE(extract(epoch FROM clock_timestamp()-min(o.created_at)),0),0))
 FROM ts.outbox o JOIN ts.effect_delivery_state d ON d.event_id=o.event_id WHERE d.confirmed_at IS NULL
$$;

REVOKE ALL ON ts.effect_delivery_state FROM PUBLIC;
REVOKE ALL ON FUNCTION ts.create_effect_delivery_state(),ts.preserve_effect_command(),ts.preserve_effect_delivery(),
 ts.effect_relay_ready(),ts.claim_effect(audit.reference),ts.confirm_effect(audit.reference),
 ts.retry_effect(audit.reference),ts.effect_relay_backlog() FROM PUBLIC;
GRANT SELECT ON ts.effect_delivery_state TO rac_backup;
