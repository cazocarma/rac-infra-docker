-- P08: authenticated positive approval with revalidation at decision time.
-- No login, catalog approval (D04) or public read cutover is provisioned here.
SET LOCAL lock_timeout='2s';

-- Approval command shape, recorded with each decision event for replay checks.
-- requirements lists what the server evaluated in its owner-side transaction;
-- a disabled check is recorded as false, never inferred as satisfied.
CREATE FUNCTION listing_review.approval_command(
 p_revision audit.reference,p_expected bigint,p_hash audit.digest,
 p_listing_policy text,p_requirements jsonb
) RETURNS jsonb LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('revision_id',p_revision,'expected_version',p_expected::text,
  'sha256',p_hash,'decision','approved','listing_policy_version',p_listing_policy,
  'requirements',p_requirements)
$$;

-- First step of an approval transaction. Locks the listing so a concurrent
-- submission/decision waits, and returns only the owner subject the server
-- needs to evaluate documents/identity with its own owner credential. A replay
-- of a recorded event skips evaluation; approve() then returns its result.
CREATE FUNCTION listing_review.approval_context(
 p_event audit.reference,p_revision audit.reference,p_expected bigint,p_hash audit.digest
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
 listing public.listings%ROWTYPE;
 revision public.listing_revisions%ROWTYPE;
 owner_subject text; prior_command jsonb;
BEGIN
 IF NOT listing_review.ready() THEN
  RAISE EXCEPTION 'listing_review_not_ready' USING ERRCODE='42501';
 END IF;
 IF p_event IS NULL OR p_revision IS NULL OR p_expected IS NULL OR p_expected<0
 OR p_expected=9223372036854775807 OR p_hash IS NULL THEN
  RAISE EXCEPTION 'invalid_listing_review_command' USING ERRCODE='22023';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('rac.listing.review:'||p_event::text,0));
 -- A retry reuses the requirements recorded for the event; approve() still
 -- compares the full command, actor, login and policy before replaying.
 SELECT command INTO prior_command FROM listing_review.decision_events WHERE event_id=p_event;
 IF FOUND THEN
  IF prior_command->>'decision'<>'approved' OR jsonb_typeof(prior_command->'requirements')<>'object' THEN
   RAISE EXCEPTION 'listing_review_event_conflict' USING ERRCODE='23505';
  END IF;
  RETURN jsonb_build_object('replay',true,'requirements',prior_command->'requirements');
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
 SELECT u.keycloak_id INTO STRICT owner_subject FROM public.compa_perfil cp
 JOIN public.usuario u ON u.id=cp.usuario_id WHERE cp.id=listing.compa_id FOR KEY SHARE OF cp,u;
 RETURN jsonb_build_object('replay',false,'owner_subject',owner_subject);
END $$;

CREATE FUNCTION listing_review.approve(
 p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_revision audit.reference,p_expected bigint,p_hash audit.digest,
 p_listing_policy text,p_requirements jsonb,p_allow_proposed boolean
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
   OR prior.policy_version<>p_policy OR prior.command<>command THEN
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
 -- P09 has no reviewed media promotion yet. A revision that references a photo
 -- cannot be approved until its approved object exists (fail closed).
 IF COALESCE(revision.payload->>'photo_version','')<>'' THEN
  RAISE EXCEPTION 'listing_photo_unapproved' USING ERRCODE='55000';
 END IF;
 INSERT INTO public.listing_revision_decisions
 (revision_id,action,reviewer_subject,reason_code,note_to_user_key)
 VALUES(p_revision,'approved',p_actor::text,'approved','listingApproved');
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

REVOKE ALL ON FUNCTION listing_review.approval_command(audit.reference,bigint,audit.digest,text,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION listing_review.approval_context(audit.reference,audit.reference,bigint,audit.digest) FROM PUBLIC;
REVOKE ALL ON FUNCTION listing_review.approve(audit.reference,audit.reference,audit.reference,
 audit.reference,bigint,audit.digest,text,jsonb,boolean) FROM PUBLIC;
-- No application role receives approval authority automatically. A dedicated
-- function-only login is provisioned separately after explicit opt-in.
