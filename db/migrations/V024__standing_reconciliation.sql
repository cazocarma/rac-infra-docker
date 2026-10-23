SET search_path TO public;

-- Durable provenance, not a permission cache. Only the booking owner writes it
-- in the same transaction as the checked business operation.
CREATE TABLE match_booking_standing (
 sesion_id uuid PRIMARY KEY REFERENCES sesion(id) ON DELETE CASCADE,
 client_version bigint NOT NULL CHECK(client_version>0),
 compa_version bigint NOT NULL CHECK(compa_version>0),
 authorized_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON match_booking_standing FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON match_booking_standing TO rac_match;
GRANT SELECT ON match_booking_standing TO rac_standing_match,rac_backup;

-- Reconciliation reuses the authenticated event identity, never invents one.
ALTER TABLE match_standing_inbox ADD CONSTRAINT standing_inbox_provenance
 UNIQUE(event_id,subject_id,version);
ALTER TABLE match_standing_projection ADD COLUMN source_event_id uuid;
ALTER TABLE match_standing_projection ADD COLUMN reconciled_at timestamptz
 NOT NULL DEFAULT '-infinity';
UPDATE match_standing_projection p SET source_event_id=(
 SELECT event_id FROM match_standing_inbox i
 WHERE i.subject_id=p.subject_id AND i.version=p.version ORDER BY event_id LIMIT 1
) WHERE p.version>0;
ALTER TABLE match_standing_projection ADD CONSTRAINT standing_projection_source
 FOREIGN KEY(source_event_id,subject_id,version)
 REFERENCES match_standing_inbox(event_id,subject_id,version);
ALTER TABLE match_standing_projection ADD CONSTRAINT standing_projection_provenance
 CHECK((version=0 AND source_event_id IS NULL) OR (version>0 AND source_event_id IS NOT NULL));
CREATE INDEX standing_reconcile_due ON match_standing_projection(reconciled_at,subject_id)
 WHERE status IN('suspended','banned');
