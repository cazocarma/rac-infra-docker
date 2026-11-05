-- Only exact, pending listing references can resolve private normalized JPEGs.
-- Every resolution is audited before its result may leave the owner process.
SET LOCAL lock_timeout='2s';
ALTER TABLE listing_review.access_events DROP CONSTRAINT access_events_kind_check;
ALTER TABLE listing_review.access_events ADD CONSTRAINT access_events_kind_check
 CHECK(kind IN('queue','revision','photo'));

CREATE FUNCTION listing_review.photo(
 p_event audit.reference,p_actor audit.reference,p_policy audit.reference,p_revision audit.reference
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE body jsonb;
BEGIN
 IF NOT listing_review.ready() THEN
  RAISE EXCEPTION 'listing_review_not_ready' USING ERRCODE='42501';
 END IF;
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_revision IS NULL THEN
  RAISE EXCEPTION 'invalid_listing_review_query' USING ERRCODE='22023';
 END IF;
 SELECT jsonb_build_object('revision_id',r.id,'listing_version',l.version::text,
  'revision_sha256',encode(r.payload_hash,'hex'),'object_key',p.object_key,
  'sha256',encode(p.normalized_sha256,'hex'),'size',p.normalized_size)
 INTO body FROM public.listings l
 JOIN public.listing_revisions r ON r.id=l.pending_revision_id
 JOIN photo.listing_references ref ON ref.revision_id=r.id AND ref.listing_id=l.id
 JOIN photo.processing_results p ON p.asset_id=ref.asset_id AND p.attempt_id=ref.attempt_id
  AND p.normalized_sha256=ref.normalized_sha256 AND p.normalized_size=ref.normalized_size
 WHERE r.id=p_revision AND p.disposition='needs_review'
 AND NOT EXISTS(SELECT FROM public.listing_revision_decisions d WHERE d.revision_id=r.id);
 INSERT INTO listing_review.access_events(event_id,human_actor,policy_version,resource_id,kind,outcome,command)
 VALUES(p_event,p_actor,p_policy,p_revision,'photo',CASE WHEN body IS NULL THEN 'not_found' ELSE 'read' END,
  jsonb_build_object('revision_id',p_revision,'sha256',body->'sha256',
   'listing_version',body->'listing_version','revision_sha256',body->'revision_sha256'));
 PERFORM audit.append(p_event,'evidence.accessed',p_revision,'case_review',p_policy);
 RETURN body;
END $$;
REVOKE ALL ON FUNCTION listing_review.photo(audit.reference,audit.reference,audit.reference,audit.reference) FROM PUBLIC;
-- No grants here. Explicit reader provisioning adds this function; customer,
-- corrector and approver credentials receive no image lookup authority.
