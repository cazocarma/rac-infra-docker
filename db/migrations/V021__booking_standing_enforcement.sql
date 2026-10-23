SET search_path=public;
-- Match-owned durable consumer state; no permissions on user authority tables.
CREATE TABLE match_standing_projection (
 subject_id uuid PRIMARY KEY REFERENCES usuario(id),
 version bigint NOT NULL CHECK(version>=0),
 status text NOT NULL CHECK(status IN ('active','restricted','suspended','banned'))
);
CREATE TABLE match_standing_inbox (
 event_id uuid PRIMARY KEY,
 subject_id uuid NOT NULL REFERENCES usuario(id),
 version bigint NOT NULL CHECK(version>0),
 payload_hash bytea NOT NULL CHECK(octet_length(payload_hash)=32),
 received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE match_standing_effect (
 event_id uuid NOT NULL REFERENCES match_standing_inbox(event_id),
 sesion_id uuid NOT NULL REFERENCES sesion(id),
 effect text NOT NULL CHECK(effect IN ('cancelled_future','safety_review')),
 quota_refunded boolean NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(event_id,sesion_id),
 CHECK(effect='cancelled_future' OR NOT quota_refunded)
);
REVOKE ALL ON match_standing_projection,match_standing_inbox,match_standing_effect FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON match_standing_projection TO rac_match;
GRANT SELECT,INSERT ON match_standing_inbox,match_standing_effect TO rac_match;
GRANT SELECT ON match_standing_projection,match_standing_inbox,match_standing_effect TO rac_backup;
