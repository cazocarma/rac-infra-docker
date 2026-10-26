-- Separate operational identities; no API gains another owner's table access.
SET search_path TO public;
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['rac_standing_relay','rac_standing_match'] LOOP
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname=r) THEN EXECUTE format('CREATE ROLE %I NOLOGIN',r); END IF;
 END LOOP;
END $$;
ALTER TABLE standing.outbox ADD COLUMN attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0);
ALTER TABLE standing.outbox ADD COLUMN next_attempt_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX standing_outbox_pending ON standing.outbox(occurred_at,event_id) WHERE published_at IS NULL;
GRANT USAGE ON SCHEMA standing TO rac_standing_relay;
GRANT SELECT ON standing.outbox TO rac_standing_relay;
-- SELECT ... FOR UPDATE needs a column UPDATE grant; no command/payload changes.
GRANT UPDATE(published_at,attempts,next_attempt_at) ON standing.outbox TO rac_standing_relay;
GRANT USAGE ON SCHEMA public TO rac_standing_match;
GRANT SELECT(id,cliente_id,compa_id,fecha_inicio,estado) ON sesion TO rac_standing_match;
GRANT SELECT(sesion_id,restituido_en) ON sesion_cupo_semanal TO rac_standing_match;
GRANT SELECT ON match_standing_projection,match_standing_inbox,match_standing_effect TO rac_standing_match;
GRANT UPDATE(estado,actualizado_en) ON sesion TO rac_standing_match;
GRANT UPDATE(restituido_en) ON sesion_cupo_semanal TO rac_standing_match;
GRANT INSERT,UPDATE ON match_standing_projection TO rac_standing_match;
GRANT INSERT ON match_standing_inbox,match_standing_effect TO rac_standing_match;
CREATE TABLE match_standing_quarantine (
 payload_hash bytea PRIMARY KEY CHECK(octet_length(payload_hash)=32),
 reason text NOT NULL CHECK(reason IN('invalid_event','conflicting_event')),
 received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON match_standing_quarantine FROM PUBLIC;
GRANT SELECT,INSERT ON match_standing_quarantine TO rac_standing_match;
GRANT SELECT ON match_standing_quarantine TO rac_backup;
