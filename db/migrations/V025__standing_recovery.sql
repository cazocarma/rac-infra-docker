SET search_path TO public;

-- Recovery exposes original public event fields, never private commands or
-- relay metadata. The authority API retains its own authenticated boundary.
GRANT SELECT(event_id,subject_id,standing_version,payload) ON standing.outbox TO rac_user;
ALTER TABLE match_standing_inbox ADD CONSTRAINT standing_inbox_account_version UNIQUE(subject_id,version);
-- APIs acquire synchronous authority permits; only the independent consumer
-- identity can append delivery evidence or modify projections/work queues.
REVOKE INSERT,UPDATE ON match_standing_projection FROM rac_match;
REVOKE INSERT ON match_standing_inbox,match_standing_effect FROM rac_match;

-- Independent replay cursor: a newer broker projection does not prove that
-- every intermediate sanction and its effects have been handled.
CREATE TABLE match_standing_sync (
 subject_id uuid PRIMARY KEY REFERENCES usuario(id) ON DELETE CASCADE,
 version bigint NOT NULL DEFAULT 1 CHECK(version>=1),
 head_version bigint NOT NULL DEFAULT 1 CHECK(head_version>=version),
 checked_at timestamptz NOT NULL DEFAULT '-infinity',
 claim_token uuid,
 claimed_until timestamptz,
 CHECK((claim_token IS NULL)=(claimed_until IS NULL))
);
CREATE INDEX standing_sync_due ON match_standing_sync(checked_at,subject_id);
CREATE INDEX standing_sync_backlog ON match_standing_sync(subject_id) WHERE version<head_version;
REVOKE ALL ON match_standing_sync FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON match_standing_sync TO rac_standing_match;
GRANT SELECT ON match_standing_sync TO rac_backup;

INSERT INTO match_standing_sync(subject_id)
 SELECT cliente_id FROM sesion UNION SELECT compa_id FROM sesion;

CREATE FUNCTION enqueue_standing_sync() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 INSERT INTO public.match_standing_sync(subject_id) VALUES(NEW.cliente_id),(NEW.compa_id)
 ON CONFLICT DO NOTHING;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enqueue_standing_sync() FROM PUBLIC;
CREATE TRIGGER enqueue_standing_sync AFTER INSERT OR UPDATE OF cliente_id,compa_id ON sesion
 FOR EACH ROW EXECUTE FUNCTION enqueue_standing_sync();

-- Keep sanction work independently from current status. A reversal must not
-- abandon a partially processed batch or reopen previously affected bookings.
CREATE TABLE match_standing_sanction (
 event_id uuid PRIMARY KEY,
 subject_id uuid NOT NULL,
 version bigint NOT NULL CHECK(version>1),
 status text NOT NULL CHECK(status IN('suspended','banned')),
 reconciled_at timestamptz NOT NULL DEFAULT '-infinity',
 FOREIGN KEY(event_id,subject_id,version)
 REFERENCES match_standing_inbox(event_id,subject_id,version) ON DELETE CASCADE
);
CREATE INDEX standing_sanction_due ON match_standing_sanction(reconciled_at,event_id);
REVOKE ALL ON match_standing_sanction FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON match_standing_sanction TO rac_standing_match;
GRANT SELECT ON match_standing_sanction TO rac_backup;
INSERT INTO match_standing_sanction(event_id,subject_id,version,status)
 SELECT source_event_id,subject_id,version,status FROM match_standing_projection
 WHERE status IN('suspended','banned') AND version>1;
