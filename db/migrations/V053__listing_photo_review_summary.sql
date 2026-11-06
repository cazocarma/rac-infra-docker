-- The staff detail carries a closed summary of the exact processed photo so a
-- human can judge it next to the private preview. It never exposes OCR text,
-- spans, fingerprints, object keys or the case/evidence ids of banned-image
-- matches; only their count. Signals prioritize review and never decide it.
SET LOCAL lock_timeout='2s';

CREATE OR REPLACE FUNCTION listing_review.revision(
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
 SELECT jsonb_build_object('id',r.id,'listing_id',r.listing_id,'revision_no',r.revision_no::text,
  'listing_version',l.version::text,'listing_state',l.state,'risk_score',r.risk_score,
  'status',CASE WHEN d.action IS NOT NULL THEN d.action WHEN l.pending_revision_id=r.id THEN 'submitted' ELSE 'superseded' END,
  'is_pending',COALESCE(l.pending_revision_id=r.id,false),'is_published',l.state='published' AND l.published_revision_id=r.id,
  'submitted_at',to_char(r.submitted_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'sha256',encode(r.payload_hash,'hex'),'payload_version',r.payload_version,
  'payload',r.payload,'assessment',r.assessment,'policy_version',r.policy_version,
  'is_self',u.keycloak_id=p_actor::text,
  'photo_review',(
   SELECT jsonb_build_object(
    'sha256',encode(p.normalized_sha256,'hex'),'risk_score',p.risk_score,'disposition',p.disposition,
    'pending_checks',COALESCE((SELECT jsonb_agg(c ORDER BY o) FROM jsonb_array_elements_text(
      CASE WHEN jsonb_typeof(p.assessment->'pending_checks')='array' THEN p.assessment->'pending_checks' ELSE '[]' END
     ) WITH ORDINALITY x(c,o) WHERE o<=16 AND c ~ '^[a-z_]{1,64}$'),'[]'),
    'unevaluated',COALESCE((SELECT jsonb_agg(c ORDER BY o) FROM jsonb_array_elements_text(
      CASE WHEN jsonb_typeof(p.assessment#>'{analysis,Unevaluated}')='array' THEN p.assessment#>'{analysis,Unevaluated}' ELSE '[]' END
     ) WITH ORDINALITY x(c,o) WHERE o<=32 AND c ~ '^[a-z_]{1,64}$'),'[]'),
    'signals',COALESCE((SELECT jsonb_agg(jsonb_build_object('category',s->>'Category','rule_id',s->>'RuleID') ORDER BY o)
     FROM jsonb_array_elements(
      CASE WHEN jsonb_typeof(p.assessment#>'{analysis,Signals}')='array' THEN p.assessment#>'{analysis,Signals}' ELSE '[]' END
     ) WITH ORDINALITY x(s,o) WHERE o<=50 AND jsonb_typeof(s)='object'
      AND COALESCE(s->>'Category','') ~ '^[a-z_]{1,64}$' AND COALESCE(s->>'RuleID','') ~ '^[A-Za-z0-9._:-]{1,128}$'),'[]'),
    'similarity',jsonb_build_object(
     'state',CASE WHEN p.assessment#>>'{similarity,state}' IN('evaluated','not_configured')
      THEN p.assessment#>>'{similarity,state}' ELSE 'unknown' END,
     'match_count',CASE WHEN jsonb_typeof(p.assessment#>'{similarity,matches}')='array'
      THEN jsonb_array_length(p.assessment#>'{similarity,matches}') ELSE 0 END))
   FROM photo.listing_references ref
   JOIN photo.processing_results p ON p.asset_id=ref.asset_id AND p.attempt_id=ref.attempt_id
    AND p.normalized_sha256=ref.normalized_sha256 AND p.normalized_size=ref.normalized_size
   WHERE ref.revision_id=r.id AND ref.listing_id=l.id))
 INTO body FROM public.listing_revisions r JOIN public.listings l ON l.id=r.listing_id
 JOIN public.compa_perfil cp ON cp.id=l.compa_id JOIN public.usuario u ON u.id=cp.usuario_id
 LEFT JOIN public.listing_revision_decisions d ON d.revision_id=r.id WHERE r.id=p_revision;
 INSERT INTO listing_review.access_events(event_id,human_actor,policy_version,resource_id,kind,outcome,command)
 VALUES(p_event,p_actor,p_policy,p_revision,'revision',CASE WHEN body IS NULL THEN 'not_found' ELSE 'read' END,
  jsonb_build_object('revision_id',p_revision,'sha256',body->'sha256','listing_version',body->'listing_version'));
 PERFORM audit.append(p_event,'evidence.accessed',p_revision,'case_review',p_policy);
 RETURN body;
END $$;
REVOKE ALL ON FUNCTION listing_review.revision(audit.reference,audit.reference,audit.reference,audit.reference) FROM PUBLIC;
-- Same signature: existing explicit reader grants are kept; no new authority.
