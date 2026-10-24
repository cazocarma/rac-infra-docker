SET search_path TO public;
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='rac_standing_alert') THEN CREATE ROLE rac_standing_alert NOLOGIN; END IF;
END $$;

CREATE INDEX standing_changed_accounts ON standing.account(subject_id) WHERE version>1;

-- Account notices are not bookings; never manufacture a session reference.
ALTER TABLE notificacion ALTER COLUMN sesion_id DROP NOT NULL;
ALTER TABLE notificacion ADD CONSTRAINT notification_context CHECK(
 (tipo='estado_cuenta' AND sesion_id IS NULL) OR
 (tipo<>'estado_cuenta' AND sesion_id IS NOT NULL)
);

CREATE TABLE alert_standing_inbox (
 event_id uuid PRIMARY KEY,
 subject_id uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
 version bigint NOT NULL CHECK(version>=2),
 payload_hash bytea NOT NULL CHECK(octet_length(payload_hash)=32),
 processed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(subject_id,version)
);
CREATE TABLE alert_standing_quarantine (
 payload_hash bytea PRIMARY KEY CHECK(octet_length(payload_hash)=32),
 reason text NOT NULL CHECK(reason IN('invalid_event','event_id_conflict')),
 received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE alert_standing_sync (
 subject_id uuid PRIMARY KEY REFERENCES usuario(id) ON DELETE CASCADE,
 version bigint NOT NULL DEFAULT 1 CHECK(version>=1),
 head_version bigint NOT NULL DEFAULT 1 CHECK(head_version>=version),
 checked_at timestamptz NOT NULL DEFAULT '-infinity',
 claim_token uuid,
 claimed_until timestamptz,
 CHECK((claim_token IS NULL)=(claimed_until IS NULL))
);
CREATE INDEX alert_standing_sync_due ON alert_standing_sync(checked_at,subject_id);
CREATE INDEX alert_standing_sync_backlog ON alert_standing_sync(subject_id) WHERE version<head_version;
CREATE TABLE alert_standing_discovery (
 singleton boolean PRIMARY KEY CHECK(singleton),
 after_subject uuid,
 completed_at timestamptz NOT NULL DEFAULT '-infinity',
 checked_at timestamptz NOT NULL DEFAULT '-infinity',
 claim_token uuid,
 claimed_until timestamptz,
 CHECK((claim_token IS NULL)=(claimed_until IS NULL))
);
INSERT INTO alert_standing_discovery(singleton) VALUES(true);

REVOKE ALL ON alert_standing_inbox,alert_standing_quarantine,alert_standing_sync,alert_standing_discovery FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO rac_standing_alert;
GRANT SELECT(id) ON usuario TO rac_standing_alert;
GRANT SELECT,INSERT ON alert_standing_inbox,alert_standing_quarantine TO rac_standing_alert;
GRANT SELECT,INSERT,UPDATE ON alert_standing_sync TO rac_standing_alert;
GRANT SELECT,UPDATE ON alert_standing_discovery TO rac_standing_alert;
-- No session or read-timestamp write grant. The context CHECK confines this
-- insertion path to neutral, account-only notifications.
GRANT INSERT(usuario_id,tipo,titulo,creado_en,evento_id) ON notificacion TO rac_standing_alert;
GRANT SELECT ON alert_standing_inbox,alert_standing_quarantine,alert_standing_sync,alert_standing_discovery TO rac_backup;
