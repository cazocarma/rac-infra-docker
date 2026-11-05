-- Private P09 processing only. No runtime role, policy, release or worker is
-- enabled here. Owner provisioning is explicit; no raw DML for application roles.
SET LOCAL lock_timeout='2s';

CREATE TABLE photo.processing_policies (
 pipeline_version text PRIMARY KEY CHECK(pipeline_version ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'),
 lease_seconds int NOT NULL CHECK(lease_seconds BETWEEN 1 AND 600),
 retry_seconds int NOT NULL CHECK(retry_seconds BETWEEN 0 AND 3600),
 max_attempts int NOT NULL CHECK(max_attempts BETWEEN 1 AND 20)
);
CREATE TABLE photo.processing_releases (
 pipeline_version text NOT NULL REFERENCES photo.processing_policies(pipeline_version),
 commit_sha text NOT NULL CHECK(commit_sha ~ '^[a-f0-9]{40}$'),
 image_digest text NOT NULL CHECK(image_digest ~ '^sha256:[a-f0-9]{64}$'),
 PRIMARY KEY(pipeline_version,commit_sha,image_digest)
);
CREATE TABLE photo.processing_jobs (
 asset_id uuid PRIMARY KEY REFERENCES photo.analysis_outbox(asset_id),
 attempts int NOT NULL DEFAULT 0 CHECK(attempts>=0),
 active_attempt uuid,
 available_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(available_at)),
 completed boolean NOT NULL DEFAULT false
);
CREATE TABLE photo.processing_attempts (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 asset_id uuid NOT NULL REFERENCES photo.processing_jobs(asset_id),
 attempt_no int NOT NULL CHECK(attempt_no>0),
 pipeline_version text NOT NULL,
 commit_sha text NOT NULL,
 image_digest text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(created_at)),
 expires_at timestamptz NOT NULL CHECK(isfinite(expires_at)),
 CHECK(expires_at>created_at),
 UNIQUE(asset_id,attempt_no), UNIQUE(id,asset_id),
 FOREIGN KEY(pipeline_version,commit_sha,image_digest)
  REFERENCES photo.processing_releases(pipeline_version,commit_sha,image_digest)
);
ALTER TABLE photo.processing_jobs ADD CONSTRAINT photo_active_attempt
 FOREIGN KEY(active_attempt,asset_id) REFERENCES photo.processing_attempts(id,asset_id);
CREATE TABLE photo.processing_results (
 asset_id uuid PRIMARY KEY,
 attempt_id uuid NOT NULL UNIQUE,
 object_key text NOT NULL UNIQUE CHECK(object_key=replace(attempt_id::text,'-','')||'.jpg'),
 normalized_sha256 bytea NOT NULL CHECK(octet_length(normalized_sha256)=32),
 normalized_size int NOT NULL CHECK(normalized_size BETWEEN 1 AND 5242880),
 assessment jsonb NOT NULL CHECK(jsonb_typeof(assessment)='object' AND octet_length(assessment::text)<=65536),
 disposition text NOT NULL CHECK(disposition IN('needs_review','contact_correction_required')),
 risk_score int NOT NULL CHECK(risk_score BETWEEN 0 AND 100),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(created_at)),
 FOREIGN KEY(attempt_id,asset_id) REFERENCES photo.processing_attempts(id,asset_id)
);
CREATE INDEX photo_processing_ready ON photo.processing_jobs(available_at,asset_id) WHERE NOT completed;
CREATE TRIGGER photo_attempt_immutable BEFORE UPDATE OR DELETE ON photo.processing_attempts
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();
CREATE TRIGGER photo_result_immutable BEFORE UPDATE OR DELETE ON photo.processing_results
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();

CREATE FUNCTION photo.enqueue_processing() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 INSERT INTO photo.processing_jobs(asset_id) VALUES(NEW.asset_id);
 RETURN NEW;
END $$;
CREATE TRIGGER photo_enqueue AFTER INSERT ON photo.analysis_outbox
 FOR EACH ROW EXECUTE FUNCTION photo.enqueue_processing();
INSERT INTO photo.processing_jobs(asset_id) SELECT asset_id FROM photo.analysis_outbox;

CREATE FUNCTION photo.claim_processing(p_pipeline text,p_commit text,p_image text)
 RETURNS TABLE(attempt_id text,asset_id text,object_key text,source_sha256 bytea,
 source_size int,media_type text,width int,height int,pipeline_version text)
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
 cfg photo.processing_policies; job photo.processing_jobs; src photo.sources;
 token uuid; at_time timestamptz;
BEGIN
 SELECT p.* INTO cfg FROM photo.processing_policies p
 JOIN photo.processing_releases r USING(pipeline_version)
 WHERE r.pipeline_version=p_pipeline AND r.commit_sha=p_commit AND r.image_digest=p_image;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unconfigured photo processing release' USING ERRCODE='55000'; END IF;
 SELECT j.* INTO job FROM photo.processing_jobs j JOIN photo.sources s ON s.id=j.asset_id
 WHERE NOT j.completed AND j.attempts<cfg.max_attempts AND j.available_at<=clock_timestamp()
 AND s.pipeline_version=p_pipeline
 ORDER BY j.available_at,j.asset_id FOR UPDATE OF j SKIP LOCKED LIMIT 1;
 IF NOT FOUND THEN RETURN; END IF;
 -- UPDATE on the locked job is the concurrency fence, also under stronger
 -- transaction isolation (where PostgreSQL may require transaction retry).
 at_time:=clock_timestamp(); token:=gen_random_uuid();
 INSERT INTO photo.processing_attempts(id,asset_id,attempt_no,pipeline_version,commit_sha,image_digest,created_at,expires_at)
 VALUES(token,job.asset_id,job.attempts+1,p_pipeline,p_commit,p_image,at_time,at_time+cfg.lease_seconds*interval '1 second');
 UPDATE photo.processing_jobs j SET active_attempt=token,attempts=job.attempts+1,
 available_at=at_time+(cfg.lease_seconds+cfg.retry_seconds)*interval '1 second' WHERE j.asset_id=job.asset_id;
 SELECT s.* INTO STRICT src FROM photo.sources s WHERE s.id=job.asset_id;
 RETURN QUERY SELECT replace(token::text,'-',''),src.id::text,src.object_key,src.source_sha256,
 src.source_size,src.declared_media_type,src.source_width,src.source_height,src.pipeline_version;
END $$;

CREATE FUNCTION photo.complete_processing(p_attempt uuid,p_asset uuid,p_pipeline text,p_commit text,p_image text,
 p_key text,p_digest bytea,p_size int,p_assessment jsonb,p_disposition text,p_risk int)
 RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE job photo.processing_jobs; attempt photo.processing_attempts; prior photo.processing_results; src photo.sources;
BEGIN
 SELECT j.* INTO job FROM photo.processing_jobs j WHERE j.asset_id=p_asset FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT a.* INTO attempt FROM photo.processing_attempts a WHERE a.id=p_attempt AND a.asset_id=p_asset;
 IF NOT FOUND OR (attempt.pipeline_version,attempt.commit_sha,attempt.image_digest)
  IS DISTINCT FROM (p_pipeline,p_commit,p_image) THEN RETURN false; END IF;
 SELECT r.* INTO prior FROM photo.processing_results r WHERE r.asset_id=p_asset;
 IF FOUND THEN
  IF (prior.attempt_id,prior.object_key,prior.normalized_sha256,prior.normalized_size,prior.assessment,prior.disposition,prior.risk_score)
    IS NOT DISTINCT FROM (p_attempt,p_key,p_digest,p_size,p_assessment,p_disposition,p_risk) THEN RETURN true; END IF;
  IF prior.attempt_id=p_attempt THEN RAISE EXCEPTION 'Conflicting photo processing receipt' USING ERRCODE='22000'; END IF;
  RETURN false;
 END IF;
 IF job.completed OR job.active_attempt IS DISTINCT FROM p_attempt OR attempt.expires_at<=clock_timestamp() THEN RETURN false; END IF;
 SELECT s.* INTO STRICT src FROM photo.sources s WHERE s.id=p_asset;
 IF p_key IS DISTINCT FROM replace(p_attempt::text,'-','')||'.jpg'
  OR p_assessment IS NULL OR jsonb_typeof(p_assessment) IS DISTINCT FROM 'object'
  OR p_assessment->>'source_id' IS DISTINCT FROM p_asset::text
  OR p_assessment->>'pipeline_version' IS DISTINCT FROM p_pipeline
  OR p_assessment->>'source_sha256' IS DISTINCT FROM encode(src.source_sha256,'hex')
  OR p_assessment->>'normalized_sha256' IS DISTINCT FROM encode(p_digest,'hex')
  OR p_assessment->>'disposition' IS DISTINCT FROM p_disposition
  OR p_assessment->>'risk_score' IS DISTINCT FROM p_risk::text THEN
  RAISE EXCEPTION 'Invalid photo processing receipt' USING ERRCODE='22000';
 END IF;
 INSERT INTO photo.processing_results(asset_id,attempt_id,object_key,normalized_sha256,normalized_size,assessment,disposition,risk_score)
 VALUES(p_asset,p_attempt,p_key,p_digest,p_size,p_assessment,p_disposition,p_risk);
 UPDATE photo.processing_jobs SET completed=true WHERE photo.processing_jobs.asset_id=p_asset;
 RETURN true;
END $$;

-- A caller cannot hold a successful completion transaction open past its lease.
CREATE FUNCTION photo.check_processing_lease() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF EXISTS(SELECT FROM photo.processing_attempts a WHERE a.id=NEW.attempt_id AND a.expires_at<=clock_timestamp()) THEN
  RAISE EXCEPTION 'Photo processing lease expired before commit' USING ERRCODE='40001';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER photo_processing_commit_fence AFTER INSERT ON photo.processing_results
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION photo.check_processing_lease();
REVOKE ALL ON photo.processing_policies,photo.processing_releases,photo.processing_jobs,photo.processing_attempts,photo.processing_results FROM PUBLIC;
REVOKE ALL ON FUNCTION photo.enqueue_processing(),photo.claim_processing(text,text,text),
 photo.complete_processing(uuid,uuid,text,text,text,text,bytea,int,jsonb,text,int),photo.check_processing_lease() FROM PUBLIC;
