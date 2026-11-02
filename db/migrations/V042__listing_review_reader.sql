-- P08 private reader. No public router, staff assignment or automatic approval.
-- A schema-scoped REVOKE cannot subtract the global default EXECUTE grant.
-- Future application functions created by this migrator are private by default.
ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
SET LOCAL lock_timeout='2s';
-- Customer-facing writers may submit, but never invent a staff decision or
-- promote a pointer. Remove column-level grants as well as table-level ones.
REVOKE INSERT ON public.listing_revision_decisions FROM rac_user;
REVOKE INSERT(revision_id,action,reviewer_subject,reason_code,note_to_user_key)
 ON public.listing_revision_decisions FROM rac_user;
REVOKE UPDATE(state,published_revision_id) ON public.listings FROM rac_user;
CREATE SCHEMA listing_review;
REVOKE ALL ON SCHEMA listing_review FROM PUBLIC;

CREATE TABLE listing_review.collections (
 id audit.reference PRIMARY KEY DEFAULT gen_random_uuid(),
 code text NOT NULL UNIQUE CHECK(code='pending_listings')
);
INSERT INTO listing_review.collections(code) VALUES('pending_listings');

CREATE TABLE listing_review.access_events (
 event_id audit.reference PRIMARY KEY,
 human_actor audit.reference NOT NULL,
 policy_version audit.reference NOT NULL,
 resource_id audit.reference NOT NULL,
 kind text NOT NULL CHECK(kind IN('queue','revision')),
 outcome text NOT NULL CHECK(outcome IN('read','not_found')),
 command jsonb NOT NULL CHECK(jsonb_typeof(command)='object'),
 occurred_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(occurred_at))
);
CREATE TRIGGER listing_review_access_immutable BEFORE UPDATE OR DELETE ON listing_review.access_events
 FOR EACH ROW EXECUTE FUNCTION public.reject_listing_history_mutation();

CREATE FUNCTION listing_review.ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT FROM audit.writer_principals p JOIN pg_roles r ON r.rolname=p.database_role
  JOIN audit.chain_heads h ON h.chain_id=p.chain_id WHERE p.database_role=session_user AND r.rolcanlogin)
 AND EXISTS(SELECT FROM listing_review.collections WHERE code='pending_listings')
$$;

CREATE FUNCTION listing_review.queue(
 p_event audit.reference,p_actor audit.reference,p_policy audit.reference,p_limit int,
 p_after_score int DEFAULT NULL,p_after_at timestamptz DEFAULT NULL,p_after_id uuid DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE rows jsonb; resource uuid;
BEGIN
 IF NOT listing_review.ready() THEN
  RAISE EXCEPTION 'listing_review_not_ready' USING ERRCODE='42501';
 END IF;
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50
 OR num_nonnulls(p_after_score,p_after_at,p_after_id) NOT IN(0,3)
 OR (p_after_score IS NOT NULL AND (p_after_score NOT BETWEEN 0 AND 100 OR NOT isfinite(p_after_at)
     OR p_after_id='00000000-0000-0000-0000-000000000000'::uuid)) THEN
  RAISE EXCEPTION 'invalid_listing_review_query' USING ERRCODE='22023';
 END IF;
 SELECT id INTO STRICT resource FROM listing_review.collections WHERE code='pending_listings';
 SELECT COALESCE(jsonb_agg(jsonb_build_object(
  'id',r.id,'listing_id',r.listing_id,'listing_version',r.version::text,'revision_no',r.revision_no::text,
  'risk_score',r.risk_score,'submitted_at',to_char(r.submitted_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'sha256',encode(r.payload_hash,'hex'),'policy_version',r.policy_version)
  ORDER BY r.risk_score DESC,r.submitted_at,r.id),'[]'::jsonb) INTO rows
 FROM (
  SELECT r.*,l.version FROM public.listing_revisions r JOIN public.listings l ON l.pending_revision_id=r.id
  WHERE p_after_id IS NULL OR (-r.risk_score,r.submitted_at,r.id)>(-p_after_score,p_after_at,p_after_id)
  ORDER BY r.risk_score DESC,r.submitted_at,r.id LIMIT p_limit+1
 ) r;
 INSERT INTO listing_review.access_events(event_id,human_actor,policy_version,resource_id,kind,outcome,command)
 VALUES(p_event,p_actor,p_policy,resource,'queue','read',jsonb_build_object(
  'limit',p_limit,'after_score',p_after_score,'after_at',p_after_at,'after_id',p_after_id,
  'revision_ids',(SELECT COALESCE(jsonb_agg(value->'id'),'[]'::jsonb) FROM jsonb_array_elements(rows))));
 -- actor_id is the provisioned service; the verified delegated human is above.
 -- HTTP must commit this transaction before delivering the buffered result.
 PERFORM audit.append(p_event,'evidence.accessed',resource,'case_review',p_policy);
 RETURN rows;
END $$;

CREATE FUNCTION listing_review.revision(
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
  'is_self',u.keycloak_id=p_actor::text)
 INTO body FROM public.listing_revisions r JOIN public.listings l ON l.id=r.listing_id
 JOIN public.compa_perfil cp ON cp.id=l.compa_id JOIN public.usuario u ON u.id=cp.usuario_id
 LEFT JOIN public.listing_revision_decisions d ON d.revision_id=r.id WHERE r.id=p_revision;
 INSERT INTO listing_review.access_events(event_id,human_actor,policy_version,resource_id,kind,outcome,command)
 VALUES(p_event,p_actor,p_policy,p_revision,'revision',CASE WHEN body IS NULL THEN 'not_found' ELSE 'read' END,
  jsonb_build_object('revision_id',p_revision,'sha256',body->'sha256','listing_version',body->'listing_version'));
 PERFORM audit.append(p_event,'evidence.accessed',p_revision,'case_review',p_policy);
 RETURN body;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA listing_review FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA listing_review FROM PUBLIC;
-- No application role receives raw reader authority. A dedicated login with
-- only these three entrypoints is provisioned separately after explicit opt-in.
