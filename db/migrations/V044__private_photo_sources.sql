-- P09 source ledger. Originals are private inputs, never approved/public photos.
-- No application route, bucket/IAM identity, worker or mandatory-face flag is
-- activated here. No existing profile key is certified or moved by this DDL.
SET LOCAL lock_timeout='2s';
CREATE SCHEMA photo;
REVOKE ALL ON SCHEMA photo FROM PUBLIC;

CREATE TABLE photo.sources (
 id uuid PRIMARY KEY CHECK(id<>'00000000-0000-0000-0000-000000000000'),
 owner_user_id uuid NOT NULL REFERENCES public.usuario(id),
 object_key text NOT NULL UNIQUE CHECK(object_key=replace(id::text,'-','')||'.raw'),
 source_sha256 bytea NOT NULL CHECK(octet_length(source_sha256)=32),
 source_size int NOT NULL CHECK(source_size BETWEEN 1 AND 5242880),
 declared_media_type text NOT NULL CHECK(declared_media_type IN('image/jpeg','image/png')),
 source_width int NOT NULL CHECK(source_width BETWEEN 32 AND 4096),
 source_height int NOT NULL CHECK(source_height BETWEEN 32 AND 4096),
 pipeline_version text NOT NULL CHECK(pipeline_version ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(created_at)),
 CHECK(source_width::bigint*source_height<=12000000),
 UNIQUE(id,source_sha256,source_size)
);
CREATE INDEX photo_sources_owner ON photo.sources(owner_user_id,created_at,id);

CREATE TABLE photo.upload_confirmations (
 asset_id uuid PRIMARY KEY,
 verified_sha256 bytea NOT NULL,
 verified_size int NOT NULL,
 confirmed_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(confirmed_at)),
 FOREIGN KEY(asset_id,verified_sha256,verified_size) REFERENCES photo.sources(id,source_sha256,source_size)
);
CREATE TABLE photo.analysis_outbox (
 asset_id uuid PRIMARY KEY REFERENCES photo.upload_confirmations(asset_id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(created_at))
);
CREATE INDEX photo_analysis_pending ON photo.analysis_outbox(created_at,asset_id);

CREATE FUNCTION photo.preserve_history() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 RAISE EXCEPTION 'Photo source history is append-only' USING ERRCODE='55000';
END $$;
CREATE TRIGGER photo_source_immutable BEFORE UPDATE OR DELETE ON photo.sources
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();
CREATE TRIGGER photo_confirmation_immutable BEFORE UPDATE OR DELETE ON photo.upload_confirmations
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();
CREATE TRIGGER photo_analysis_intent_immutable BEFORE UPDATE OR DELETE ON photo.analysis_outbox
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();

REVOKE ALL ON ALL TABLES IN SCHEMA photo FROM PUBLIC;
REVOKE ALL ON FUNCTION photo.preserve_history() FROM PUBLIC;
GRANT USAGE ON SCHEMA photo TO rac_user;
GRANT SELECT ON photo.sources,photo.upload_confirmations,photo.analysis_outbox TO rac_user;
GRANT INSERT(id,owner_user_id,object_key,source_sha256,source_size,declared_media_type,
 source_width,source_height,pipeline_version) ON photo.sources TO rac_user;
GRANT INSERT(asset_id,verified_sha256,verified_size) ON photo.upload_confirmations TO rac_user;
GRANT INSERT(asset_id) ON photo.analysis_outbox TO rac_user;
-- No UPDATE/DELETE, fake approvals, raw image bytes or OCR text in this ledger.
-- P12 must supply an audited erasure/hold procedure before real-data activation.
