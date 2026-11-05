-- Atomic photo receipt + decision/audit/outbox/reference/public pointer.
-- No role grants, policy seed or runtime activation. Plain approval stays
-- photo-closed by delegating with a NULL promotion reference.
SET LOCAL lock_timeout='2s';

CREATE TABLE photo.promotion_receipts (
 intent_id audit.reference PRIMARY KEY REFERENCES photo.promotion_intents(id),
 attempt_id audit.reference NOT NULL,
 version_id text NOT NULL CHECK(octet_length(version_id) BETWEEN 1 AND 2048
  AND version_id<>'null' AND version_id=btrim(version_id) AND version_id !~ '[[:cntrl:]]'),
 normalized_sha256 bytea NOT NULL CHECK(octet_length(normalized_sha256)=32),
 normalized_size int NOT NULL CHECK(normalized_size BETWEEN 1 AND 5242880),
 authorized_until timestamptz NOT NULL CHECK(isfinite(authorized_until)),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(created_at)),
 FOREIGN KEY(attempt_id,intent_id) REFERENCES photo.promotion_attempts(id,intent_id)
);
CREATE TABLE photo.approved_references (
 revision_id uuid PRIMARY KEY REFERENCES public.listing_revisions(id),
 intent_id audit.reference NOT NULL UNIQUE REFERENCES photo.promotion_receipts(intent_id),
 event_id audit.reference NOT NULL UNIQUE REFERENCES listing_review.decision_events(event_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TRIGGER photo_promotion_receipt_immutable BEFORE UPDATE OR DELETE ON photo.promotion_receipts
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();
CREATE TRIGGER photo_approved_reference_immutable BEFORE UPDATE OR DELETE ON photo.approved_references
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();

CREATE FUNCTION photo.check_promotion_receipt_commit() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE intent photo.promotion_intents%ROWTYPE; expires timestamptz;
BEGIN
 SELECT * INTO STRICT intent FROM photo.promotion_intents WHERE id=NEW.intent_id;
 SELECT expires_at INTO STRICT expires FROM photo.promotion_attempts WHERE id=NEW.attempt_id AND intent_id=NEW.intent_id;
 IF clock_timestamp()>=least(NEW.authorized_until,expires) THEN
  RAISE EXCEPTION 'listing_photo_authorization_expired' USING ERRCODE='55000';
 END IF;
 IF NEW.normalized_sha256<>intent.normalized_sha256 OR NEW.normalized_size<>intent.normalized_size
 OR NOT EXISTS(
  SELECT FROM photo.approved_references ar JOIN listing_review.decision_events e ON e.event_id=ar.event_id
  JOIN public.listing_revision_decisions d ON d.revision_id=ar.revision_id
  WHERE ar.intent_id=intent.id AND ar.revision_id=intent.revision_id AND ar.event_id=intent.event_id
   AND e.revision_id=intent.revision_id AND e.human_actor=intent.human_actor
   AND e.database_role=intent.database_role AND e.policy_version=intent.review_policy
   AND e.result->>'decision'='approved' AND d.action='approved' AND d.reviewer_subject=intent.human_actor::text) THEN
  RAISE EXCEPTION 'listing_photo_unapproved' USING ERRCODE='55000';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER photo_receipt_commit_guard AFTER INSERT ON photo.promotion_receipts
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION photo.check_promotion_receipt_commit();
REVOKE ALL ON photo.promotion_receipts,photo.approved_references FROM PUBLIC;
REVOKE ALL ON FUNCTION photo.check_promotion_receipt_commit() FROM PUBLIC;

CREATE FUNCTION listing_review.approve_core(
 p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_revision audit.reference,p_expected bigint,p_hash audit.digest,
 p_listing_policy text,p_requirements jsonb,p_allow_proposed boolean,
 p_promotion audit.reference
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
 prior listing_review.decision_events%ROWTYPE;
 listing public.listings%ROWTYPE;
 revision public.listing_revisions%ROWTYPE;
 owner_id uuid; owner_subject text; owner_status text;
 command jsonb; result jsonb;
BEGIN
 IF NOT listing_review.ready() THEN
  RAISE EXCEPTION 'listing_review_not_ready' USING ERRCODE='42501';
 END IF;
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_revision IS NULL
 OR p_expected IS NULL OR p_expected<0 OR p_expected=9223372036854775807 OR p_hash IS NULL
 OR p_listing_policy IS NULL OR p_listing_policy !~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'
 OR p_allow_proposed IS NULL OR p_requirements IS NULL OR jsonb_typeof(p_requirements)<>'object'
 OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_requirements) k)
    IS DISTINCT FROM ARRAY['allow_proposed_activities','documents','identity']
 OR jsonb_typeof(p_requirements->'documents')<>'boolean'
 OR jsonb_typeof(p_requirements->'identity')<>'boolean'
 OR p_requirements->'allow_proposed_activities'<>to_jsonb(p_allow_proposed) THEN
  RAISE EXCEPTION 'invalid_listing_review_command' USING ERRCODE='22023';
 END IF;
 command:=listing_review.approval_command(p_revision,p_expected,p_hash,p_listing_policy,p_requirements);
 PERFORM pg_advisory_xact_lock(hashtextextended('rac.listing.review:'||p_event::text,0));
 SELECT * INTO prior FROM listing_review.decision_events WHERE event_id=p_event;
 IF FOUND THEN
  IF prior.human_actor<>p_actor OR prior.database_role<>session_user
   OR prior.policy_version<>p_policy OR prior.command<>command
   OR (p_promotion IS NULL AND EXISTS(SELECT FROM photo.approved_references ar WHERE ar.event_id=p_event))
   OR (p_promotion IS NOT NULL AND NOT EXISTS(SELECT FROM photo.approved_references ar WHERE ar.event_id=p_event AND ar.intent_id=p_promotion)) THEN
   RAISE EXCEPTION 'listing_review_event_conflict' USING ERRCODE='23505';
  END IF;
  RETURN prior.result;
 END IF;
 SELECT * INTO revision FROM public.listing_revisions WHERE id=p_revision;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'listing_revision_not_found' USING ERRCODE='P0002';
 END IF;
 SELECT * INTO STRICT listing FROM public.listings WHERE id=revision.listing_id FOR NO KEY UPDATE;
 IF listing.version<>p_expected OR listing.pending_revision_id IS DISTINCT FROM p_revision
  OR encode(revision.payload_hash,'hex')<>p_hash THEN
  RAISE EXCEPTION 'listing_revision_conflict' USING ERRCODE='40001';
 END IF;
 SELECT u.id,u.keycloak_id INTO STRICT owner_id,owner_subject FROM public.compa_perfil cp
 JOIN public.usuario u ON u.id=cp.usuario_id WHERE cp.id=listing.compa_id FOR KEY SHARE OF cp,u;
 IF lower(owner_subject)=p_actor::text THEN
  RAISE EXCEPTION 'listing_self_review' USING ERRCODE='42501';
 END IF;
 -- A suspended/removed listing is an enforcement state, not a review outcome.
 IF listing.state NOT IN('unpublished','published') THEN
  RAISE EXCEPTION 'listing_not_publishable' USING ERRCODE='55000';
 END IF;
 -- The submission was evaluated under this policy (prices, areas, catalog
 -- limits). A policy change after submission requires a new submission.
 IF revision.policy_version<>p_listing_policy THEN
  RAISE EXCEPTION 'listing_policy_changed' USING ERRCODE='55000';
 END IF;
 -- Share-lock standing until commit: a concurrent sanction waits, and an
 -- approval cannot publish over one that committed first.
 SELECT status INTO owner_status FROM standing.account WHERE subject_id=owner_id FOR SHARE;
 IF NOT FOUND OR owner_status<>'active' OR EXISTS(
  SELECT FROM standing.restriction r WHERE r.subject_id=owner_id AND r.capability='publish_listing'
   AND r.starts_at<=clock_timestamp() AND (r.ends_at IS NULL OR r.ends_at>clock_timestamp())) THEN
  RAISE EXCEPTION 'listing_owner_restricted' USING ERRCODE='55000';
 END IF;
 -- Every activity must still be offered. Proposed entries are only accepted
 -- when the server's environment allows them (dev/test); D04 decides approval.
 -- Activities needing extra verification fail closed until that flow exists.
 -- Lock first so a retirement cannot commit between the check and approval.
 PERFORM 1 FROM public.activity_categories c
 WHERE c.slug IN(SELECT a->>'slug' FROM jsonb_array_elements(
  CASE WHEN jsonb_typeof(revision.payload->'activities')='array' THEN revision.payload->'activities' ELSE '[]' END) a)
 ORDER BY c.id FOR SHARE;
 IF jsonb_typeof(revision.payload->'activities')<>'array'
 OR jsonb_array_length(revision.payload->'activities')=0 OR EXISTS(
  SELECT FROM jsonb_array_elements(revision.payload->'activities') a
  LEFT JOIN public.activity_categories c ON c.slug=a->>'slug'
  WHERE c.id IS NULL OR c.status<>'active' OR c.requires_additional_verification
   OR (c.approval<>'approved' AND NOT p_allow_proposed)) THEN
  RAISE EXCEPTION 'listing_activity_unavailable' USING ERRCODE='55000';
 END IF;
 -- A photo is publishable only through the private finalization command,
 -- with a receipt linked to this exact event/actor/login/revision and source.
 IF COALESCE(revision.payload->>'photo_version','')<>'' THEN
  IF p_promotion IS NULL OR NOT EXISTS(
   SELECT FROM photo.promotion_receipts pr JOIN photo.promotion_intents pi ON pi.id=pr.intent_id
   WHERE pi.id=p_promotion AND pi.event_id=p_event AND pi.revision_id=p_revision
    AND pi.human_actor=p_actor AND pi.database_role=session_user AND pi.review_policy=p_policy
    AND pi.expected_version=p_expected AND pi.revision_sha256=p_hash AND pi.listing_policy=p_listing_policy
    AND pi.asset_id::text=revision.payload->>'photo_version'
    AND pr.normalized_sha256=pi.normalized_sha256 AND pr.normalized_size=pi.normalized_size) THEN
   RAISE EXCEPTION 'listing_photo_unapproved' USING ERRCODE='55000';
  END IF;
 ELSIF p_promotion IS NOT NULL THEN
  RAISE EXCEPTION 'listing_photo_unapproved' USING ERRCODE='55000';
 END IF;
 INSERT INTO public.listing_revision_decisions
 (revision_id,action,reviewer_subject,reason_code,note_to_user_key)
 VALUES(p_revision,'approved',p_actor::text,'approved','listingApproved');
 IF p_promotion IS NOT NULL THEN
  INSERT INTO photo.approved_references(revision_id,intent_id,event_id) VALUES(p_revision,p_promotion,p_event);
 END IF;
 UPDATE public.listings SET state='published',published_revision_id=p_revision,
  pending_revision_id=NULL,version=version+1 WHERE id=listing.id;
 result:=jsonb_build_object('event_id',p_event,'revision_id',p_revision,'listing_id',listing.id,
  'listing_version',(p_expected+1)::text,'decision','approved','note_to_user_key','listingApproved');
 INSERT INTO listing_review.decision_events
 (event_id,revision_id,human_actor,database_role,policy_version,command,result)
 VALUES(p_event,p_revision,p_actor,session_user,p_policy,command,result);
 INSERT INTO listing_review.outbox(event_id,recipient_user_id,kind,payload)
 VALUES(p_event,owner_id,'listing.reviewed.v1',result);
 PERFORM audit.append(p_event,'listing.reviewed',p_revision,'case_review',p_policy);
 RETURN result;
END $$;

REVOKE ALL ON FUNCTION listing_review.approve_core(audit.reference,audit.reference,audit.reference,
 audit.reference,bigint,audit.digest,text,jsonb,boolean,audit.reference) FROM PUBLIC;

-- Preserve the existing function OID/grants and its no-photo contract. The
-- private implementation is not granted to any ingress role.
CREATE OR REPLACE FUNCTION listing_review.approve(
 p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_revision audit.reference,p_expected bigint,p_hash audit.digest,
 p_listing_policy text,p_requirements jsonb,p_allow_proposed boolean
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT listing_review.approve_core(p_event,p_actor,p_policy,p_revision,p_expected,p_hash,
  p_listing_policy,p_requirements,p_allow_proposed,NULL::audit.reference)
$$;

-- Retry lookup before any new S3 I/O. It returns only the original command's
-- minimal result and never changes a public pointer or consumes a new attempt.
CREATE FUNCTION listing_review.photo_promotion_result(
 p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_revision audit.reference,p_expected bigint,p_hash audit.digest,
 p_listing_policy text,p_pipeline text,p_target audit.reference
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE prior listing_review.decision_events%ROWTYPE; intent photo.promotion_intents%ROWTYPE;
BEGIN
 IF NOT listing_review.ready() THEN RAISE EXCEPTION 'listing_review_not_ready' USING ERRCODE='42501'; END IF;
 IF num_nulls(p_event,p_actor,p_policy,p_revision,p_expected,p_hash,p_listing_policy,p_pipeline,p_target)<>0
 OR p_expected<0 OR p_expected=9223372036854775807 THEN
  RAISE EXCEPTION 'invalid_listing_review_command' USING ERRCODE='22023';
 END IF;
 SELECT * INTO prior FROM listing_review.decision_events WHERE event_id=p_event;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO intent FROM photo.promotion_intents WHERE event_id=p_event;
 IF NOT FOUND OR intent.human_actor<>p_actor OR intent.database_role<>session_user
 OR intent.review_policy<>p_policy OR intent.revision_id<>p_revision OR intent.expected_version<>p_expected
 OR intent.revision_sha256<>p_hash OR intent.listing_policy<>p_listing_policy
 OR intent.pipeline_version<>p_pipeline OR intent.target_id<>p_target
 OR prior.human_actor<>p_actor OR prior.database_role<>session_user OR prior.policy_version<>p_policy
 OR prior.revision_id<>p_revision OR prior.result->>'decision' IS DISTINCT FROM 'approved'
 OR NOT EXISTS(SELECT FROM photo.approved_references WHERE intent_id=intent.id AND event_id=p_event AND revision_id=p_revision) THEN
  RAISE EXCEPTION 'listing_review_event_conflict' USING ERRCODE='23505';
 END IF;
 RETURN prior.result;
END $$;

CREATE FUNCTION listing_review.finalize_photo_promotion(
 p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_revision audit.reference,p_expected bigint,p_hash audit.digest,
 p_listing_policy text,p_requirements jsonb,p_allow_proposed boolean,
 p_intent audit.reference,p_attempt audit.reference,p_version text,p_digest bytea,p_size int,
 p_authorized_until timestamptz
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE intent photo.promotion_intents%ROWTYPE; prior jsonb; expires timestamptz;
BEGIN
 IF NOT listing_review.ready() THEN RAISE EXCEPTION 'listing_review_not_ready' USING ERRCODE='42501'; END IF;
 IF num_nulls(p_event,p_actor,p_policy,p_revision,p_expected,p_hash,p_listing_policy,p_requirements,p_allow_proposed,
  p_intent,p_attempt,p_version,p_digest,p_size,p_authorized_until)<>0 THEN
  RAISE EXCEPTION 'invalid_listing_review_command' USING ERRCODE='22023';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('rac.listing.review:'||p_event::text,0));
 SELECT * INTO intent FROM photo.promotion_intents WHERE id=p_intent;
 IF NOT FOUND OR intent.event_id<>p_event OR intent.human_actor<>p_actor OR intent.database_role<>session_user
 OR intent.review_policy<>p_policy OR intent.revision_id<>p_revision OR intent.expected_version<>p_expected
 OR intent.revision_sha256<>p_hash OR intent.listing_policy<>p_listing_policy
 OR intent.normalized_sha256<>p_digest OR intent.normalized_size<>p_size THEN
  RAISE EXCEPTION 'listing_review_event_conflict' USING ERRCODE='23505';
 END IF;
 prior:=listing_review.photo_promotion_result(p_event,p_actor,p_policy,p_revision,p_expected,p_hash,
  p_listing_policy,intent.pipeline_version,intent.target_id);
 IF prior IS NOT NULL THEN
  IF NOT EXISTS(SELECT FROM photo.promotion_receipts WHERE intent_id=p_intent AND version_id=p_version
    AND normalized_sha256=p_digest AND normalized_size=p_size)
  OR p_requirements->'allow_proposed_activities' IS DISTINCT FROM to_jsonb(p_allow_proposed)
  OR (SELECT command FROM listing_review.decision_events WHERE event_id=p_event)
   <>listing_review.approval_command(p_revision,p_expected,p_hash,p_listing_policy,p_requirements) THEN
   RAISE EXCEPTION 'listing_review_event_conflict' USING ERRCODE='23505';
  END IF;
  RETURN prior;
 END IF;
 IF NOT isfinite(p_authorized_until) OR p_authorized_until<=clock_timestamp()
 OR p_authorized_until>clock_timestamp()+interval '5 minutes' THEN
  RAISE EXCEPTION 'listing_photo_authorization_expired' USING ERRCODE='55000';
 END IF;
 SELECT expires_at INTO expires FROM photo.promotion_attempts WHERE id=p_attempt AND intent_id=p_intent;
 IF NOT FOUND OR expires<=clock_timestamp() THEN
  RAISE EXCEPTION 'listing_photo_authorization_expired' USING ERRCODE='55000';
 END IF;
 PERFORM 1 FROM photo.promotion_gates g JOIN photo.promotion_policies p ON p.policy_version=g.policy_version
 WHERE p.policy_version=p_policy AND p.listing_policy=p_listing_policy AND p.pipeline_version=intent.pipeline_version
  AND p.target_id=intent.target_id AND g.enabled FOR SHARE OF g;
 IF NOT FOUND OR NOT EXISTS(SELECT FROM photo.ready_listing_sources s WHERE s.asset_id=intent.asset_id
  AND s.attempt_id=intent.processing_attempt_id AND s.pipeline_version=intent.pipeline_version
  AND s.normalized_sha256=intent.normalized_sha256 AND s.normalized_size=intent.normalized_size) THEN
  RAISE EXCEPTION 'listing_photo_unapproved' USING ERRCODE='55000';
 END IF;
 INSERT INTO photo.promotion_receipts(intent_id,attempt_id,version_id,normalized_sha256,normalized_size,authorized_until)
 VALUES(p_intent,p_attempt,p_version,p_digest,p_size,p_authorized_until);
 RETURN listing_review.approve_core(p_event,p_actor,p_policy,p_revision,p_expected,p_hash,
  p_listing_policy,p_requirements,p_allow_proposed,p_intent);
END $$;
REVOKE ALL ON FUNCTION listing_review.photo_promotion_result(audit.reference,audit.reference,audit.reference,
 audit.reference,bigint,audit.digest,text,text,audit.reference) FROM PUBLIC;
REVOKE ALL ON FUNCTION listing_review.finalize_photo_promotion(audit.reference,audit.reference,audit.reference,
 audit.reference,bigint,audit.digest,text,jsonb,boolean,audit.reference,audit.reference,text,bytea,int,timestamptz) FROM PUBLIC;
