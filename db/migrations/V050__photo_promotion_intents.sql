-- Durable authorization before external media I/O. No approval gate changes,
-- role grants, destination/policy seed or application activation.
SET LOCAL lock_timeout='2s';

CREATE TABLE photo.media_targets (
 id audit.reference PRIMARY KEY,
 locator_sha256 bytea NOT NULL CHECK(octet_length(locator_sha256)=32),
 bucket_name text NOT NULL CHECK(bucket_name ~ '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'),
 region text NOT NULL CHECK(region ~ '^[A-Za-z0-9][A-Za-z0-9-]{0,63}$'),
 UNIQUE(locator_sha256,bucket_name,region)
);
CREATE TABLE photo.promotion_policies (
 policy_version audit.reference PRIMARY KEY,
 listing_policy text NOT NULL CHECK(listing_policy ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'),
 pipeline_version text NOT NULL REFERENCES photo.processing_policies(pipeline_version),
 target_id audit.reference NOT NULL REFERENCES photo.media_targets(id),
 UNIQUE(policy_version,listing_policy,pipeline_version,target_id)
);
CREATE TABLE photo.promotion_gates (
 policy_version audit.reference PRIMARY KEY REFERENCES photo.promotion_policies(policy_version),
 enabled boolean NOT NULL DEFAULT false
);
CREATE TRIGGER photo_target_immutable BEFORE UPDATE OR DELETE ON photo.media_targets
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();
CREATE TRIGGER photo_promotion_policy_immutable BEFORE UPDATE OR DELETE ON photo.promotion_policies
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();

ALTER TABLE photo.listing_references ADD CONSTRAINT photo_listing_promotion_reference
 UNIQUE(revision_id,asset_id,attempt_id,normalized_sha256,normalized_size);
CREATE TABLE photo.promotion_intents (
 id audit.reference PRIMARY KEY DEFAULT gen_random_uuid(),
 event_id audit.reference NOT NULL UNIQUE,
 revision_id uuid NOT NULL,
 human_actor audit.reference NOT NULL,
 database_role name NOT NULL,
 review_policy audit.reference NOT NULL,
 expected_version bigint NOT NULL CHECK(expected_version BETWEEN 0 AND 9223372036854775806),
 revision_sha256 audit.digest NOT NULL,
 listing_policy text NOT NULL CHECK(listing_policy ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'),
 pipeline_version text NOT NULL,
 target_id audit.reference NOT NULL,
 asset_id uuid NOT NULL,
 processing_attempt_id uuid NOT NULL,
 normalized_sha256 bytea NOT NULL CHECK(octet_length(normalized_sha256)=32),
 normalized_size int NOT NULL CHECK(normalized_size BETWEEN 1 AND 5242880),
 destination_key text GENERATED ALWAYS AS (replace(id::text,'-','')||'.jpg') STORED UNIQUE,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(created_at)),
 FOREIGN KEY(review_policy,listing_policy,pipeline_version,target_id)
  REFERENCES photo.promotion_policies(policy_version,listing_policy,pipeline_version,target_id),
 FOREIGN KEY(revision_id,asset_id,processing_attempt_id,normalized_sha256,normalized_size)
  REFERENCES photo.listing_references(revision_id,asset_id,attempt_id,normalized_sha256,normalized_size)
);
CREATE INDEX photo_promotion_revision ON photo.promotion_intents(revision_id,event_id);
CREATE TRIGGER photo_promotion_intent_immutable BEFORE UPDATE OR DELETE ON photo.promotion_intents
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();
CREATE TABLE photo.promotion_attempts (
 id audit.reference PRIMARY KEY DEFAULT gen_random_uuid(),
 intent_id audit.reference NOT NULL REFERENCES photo.promotion_intents(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(created_at)),
 expires_at timestamptz NOT NULL CHECK(isfinite(expires_at) AND expires_at>created_at),
 UNIQUE(id,intent_id)
);
CREATE TRIGGER photo_promotion_attempt_immutable BEFORE UPDATE OR DELETE ON photo.promotion_attempts
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();

CREATE FUNCTION listing_review.prepare_photo_promotion(
 p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_revision audit.reference,p_expected bigint,p_hash audit.digest,
 p_listing_policy text,p_pipeline text,p_target audit.reference
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
 listing public.listings%ROWTYPE;
 revision public.listing_revisions%ROWTYPE;
 ref photo.listing_references%ROWTYPE;
 intent photo.promotion_intents%ROWTYPE;
 attempt photo.promotion_attempts%ROWTYPE;
 target photo.media_targets%ROWTYPE;
 owner_id uuid; owner_subject text; owner_status text; reused boolean;
BEGIN
 IF NOT listing_review.ready() THEN
  RAISE EXCEPTION 'listing_review_not_ready' USING ERRCODE='42501';
 END IF;
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_revision IS NULL
 OR p_expected IS NULL OR p_expected<0 OR p_expected=9223372036854775807 OR p_hash IS NULL
 OR p_listing_policy IS NULL OR p_listing_policy !~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'
 OR p_pipeline IS NULL OR p_target IS NULL THEN
  RAISE EXCEPTION 'invalid_listing_review_command' USING ERRCODE='22023';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('rac.listing.review:'||p_event::text,0));
 IF EXISTS(SELECT FROM listing_review.decision_events WHERE event_id=p_event) THEN
  -- Finalized media replay is added with the atomic finalization command. Until
  -- then this entrypoint must not reinterpret a different existing decision.
  RAISE EXCEPTION 'listing_review_event_conflict' USING ERRCODE='23505';
 END IF;
 SELECT * INTO intent FROM photo.promotion_intents WHERE event_id=p_event;
 reused:=FOUND;
 IF reused AND (intent.human_actor<>p_actor OR intent.database_role<>session_user
  OR intent.review_policy<>p_policy OR intent.revision_id<>p_revision
  OR intent.expected_version<>p_expected OR intent.revision_sha256<>p_hash
  OR intent.listing_policy<>p_listing_policy OR intent.pipeline_version<>p_pipeline
  OR intent.target_id<>p_target) THEN
  RAISE EXCEPTION 'listing_review_event_conflict' USING ERRCODE='23505';
 END IF;
 SELECT * INTO revision FROM public.listing_revisions WHERE id=p_revision;
 IF NOT FOUND THEN RAISE EXCEPTION 'listing_revision_not_found' USING ERRCODE='P0002'; END IF;
 SELECT * INTO STRICT listing FROM public.listings WHERE id=revision.listing_id FOR NO KEY UPDATE;
 IF listing.version<>p_expected OR listing.pending_revision_id IS DISTINCT FROM p_revision
 OR encode(revision.payload_hash,'hex')<>p_hash OR EXISTS(
  SELECT FROM public.listing_revision_decisions WHERE revision_id=p_revision) THEN
  RAISE EXCEPTION 'listing_revision_conflict' USING ERRCODE='40001';
 END IF;
 IF listing.state NOT IN('unpublished','published') THEN
  RAISE EXCEPTION 'listing_not_publishable' USING ERRCODE='55000';
 END IF;
 IF revision.policy_version<>p_listing_policy THEN
  RAISE EXCEPTION 'listing_policy_changed' USING ERRCODE='55000';
 END IF;
 SELECT u.id,u.keycloak_id INTO STRICT owner_id,owner_subject FROM public.compa_perfil cp
 JOIN public.usuario u ON u.id=cp.usuario_id WHERE cp.id=listing.compa_id FOR KEY SHARE OF cp,u;
 IF lower(owner_subject)=p_actor::text THEN
  RAISE EXCEPTION 'listing_self_review' USING ERRCODE='42501';
 END IF;
 SELECT status INTO owner_status FROM standing.account WHERE subject_id=owner_id FOR SHARE;
 IF NOT FOUND OR owner_status<>'active' OR EXISTS(
  SELECT FROM standing.restriction WHERE subject_id=owner_id AND capability='publish_listing'
   AND starts_at<=clock_timestamp() AND (ends_at IS NULL OR ends_at>clock_timestamp())) THEN
  RAISE EXCEPTION 'listing_owner_restricted' USING ERRCODE='55000';
 END IF;
 PERFORM 1 FROM photo.promotion_policies p JOIN photo.promotion_gates g ON g.policy_version=p.policy_version
 WHERE p.policy_version=p_policy AND p.listing_policy=p_listing_policy
  AND p.pipeline_version=p_pipeline AND p.target_id=p_target AND g.enabled
 FOR SHARE OF g;
 IF NOT FOUND THEN RAISE EXCEPTION 'listing_photo_unapproved' USING ERRCODE='55000'; END IF;
 SELECT * INTO STRICT target FROM photo.media_targets WHERE id=p_target;
 SELECT lr.* INTO ref FROM photo.listing_references lr
 JOIN photo.ready_listing_sources s ON s.asset_id=lr.asset_id AND s.attempt_id=lr.attempt_id
  AND s.normalized_sha256=lr.normalized_sha256 AND s.normalized_size=lr.normalized_size
 WHERE lr.revision_id=p_revision AND s.pipeline_version=p_pipeline;
 IF NOT FOUND THEN RAISE EXCEPTION 'listing_photo_unapproved' USING ERRCODE='55000'; END IF;
 IF NOT reused THEN
  INSERT INTO photo.promotion_intents(event_id,revision_id,human_actor,database_role,review_policy,
   expected_version,revision_sha256,listing_policy,pipeline_version,target_id,asset_id,
   processing_attempt_id,normalized_sha256,normalized_size)
  VALUES(p_event,p_revision,p_actor,session_user,p_policy,p_expected,p_hash,p_listing_policy,p_pipeline,p_target,
   ref.asset_id,ref.attempt_id,ref.normalized_sha256,ref.normalized_size) RETURNING * INTO intent;
 END IF;
 INSERT INTO photo.promotion_attempts(intent_id,expires_at)
 VALUES(intent.id,clock_timestamp()+interval '2 minutes') RETURNING * INTO attempt;
 INSERT INTO listing_review.access_events(event_id,human_actor,policy_version,resource_id,kind,outcome,command)
 VALUES(attempt.id,p_actor,p_policy,p_revision,'photo','read',jsonb_build_object(
  'purpose','promotion','intent_id',intent.id,'attempt_id',attempt.id,
  'revision_id',p_revision,'sha256',p_hash,'listing_version',p_expected::text));
 PERFORM audit.append(attempt.id,'evidence.accessed',p_revision,'case_review',p_policy);
 RETURN jsonb_build_object('intent_id',intent.id,'attempt_id',attempt.id,'intent_reused',reused,
  'event_id',p_event,'revision_id',p_revision,'listing_id',listing.id,'expected_version',p_expected::text,
  'sha256',p_hash,'human_actor',p_actor,'review_policy',p_policy,'listing_policy',p_listing_policy,
  'asset_id',ref.asset_id,'processing_attempt_id',ref.attempt_id,'pipeline_version',p_pipeline,
  'source_key',replace(ref.attempt_id::text,'-','')||'.jpg',
  'normalized_sha256',encode(ref.normalized_sha256,'hex'),'normalized_size',ref.normalized_size,
  'destination_id',target.id,'destination_bucket',target.bucket_name,'destination_region',target.region,
  'destination_locator_sha256',encode(target.locator_sha256,'hex'),'destination_key',intent.destination_key,
  'attempt_expires_at',to_char(attempt.expires_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
END $$;
REVOKE ALL ON photo.media_targets,photo.promotion_policies,photo.promotion_gates,
 photo.promotion_intents,photo.promotion_attempts FROM PUBLIC;
REVOKE ALL ON FUNCTION listing_review.prepare_photo_promotion(audit.reference,audit.reference,audit.reference,
 audit.reference,bigint,audit.digest,text,text,audit.reference) FROM PUBLIC;
