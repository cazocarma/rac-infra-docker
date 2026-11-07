-- P11 hide_listing: an action hides the exact listing revision reported in its
-- case. T&S records the decision and its target; user, the owner of listings,
-- applies it as the existing `suspended` enforcement state and restores the
-- listing when the action is revoked (including an overturned appeal).
-- No duration: the hold lasts until revocation (D06 keeps preventive expiry
-- criteria open). Public reads still use the legacy profile until the P08
-- cutover; approval already refuses suspended listings.
SET LOCAL lock_timeout='2s';

-- T&S: the decided target travels with the action and its revocation.
ALTER TABLE ts.actions ADD COLUMN target_type text, ADD COLUMN target_id uuid;
ALTER TABLE ts.actions ADD CONSTRAINT action_target_shape CHECK(
 (target_type IS NULL)=(target_id IS NULL)
 AND (target_type IS NULL OR target_type='listing_revision')
 AND (target_type IS NULL OR kind IN('hide_listing','revocation')));
-- New hide_listing actions must name a target and carry no duration. Any
-- earlier untargeted row stays as recorded history (NOT VALID).
ALTER TABLE ts.actions ADD CONSTRAINT hide_listing_target CHECK(
 kind<>'hide_listing' OR (target_id IS NOT NULL AND duration_hours IS NULL)) NOT VALID;

CREATE OR REPLACE FUNCTION ts.effect(p_action ts.actions) RETURNS void
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 -- Serialize before allocating the outbox ID, across different cases of the
 -- same principal. A visible successor cannot overtake an uncommitted source.
 PERFORM pg_advisory_xact_lock(hashtextextended('ts-effect-source:'||p_action.subject::text,0));
 -- Untargeted bodies stay byte-identical to earlier producers.
 INSERT INTO ts.outbox(event_type,payload) VALUES('ts.action.effective.v1',jsonb_build_object(
  'action_id',p_action.id,'case_id',p_action.case_id,'subject',p_action.subject,'kind',p_action.kind,
  'reason_code',p_action.reason_code,'policy_version',p_action.policy_version,
  'duration_hours',p_action.duration_hours,'notice_key',p_action.notice_key,'revokes',p_action.revokes,
  'effective_at',to_char(p_action.effective_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'))
  || CASE WHEN p_action.target_id IS NULL THEN '{}'::jsonb
     ELSE jsonb_build_object('target',jsonb_build_object('type',p_action.target_type,'id',p_action.target_id)) END);
 INSERT INTO ts.case_events(case_id,kind,actor,resource)
 VALUES(p_action.case_id,CASE WHEN p_action.kind='revocation' THEN 'action_revoked' ELSE 'action_effective' END,
  COALESCE(p_action.approved_by,p_action.proposed_by),p_action.id);
END $$;

-- A revocation repeats the target of the action it revokes.
CREATE OR REPLACE FUNCTION ts.revoke(p_case uuid,p_target ts.actions,p_actor audit.reference,p_reason text) RETURNS ts.actions
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE created ts.actions%ROWTYPE;
BEGIN
 INSERT INTO ts.actions(case_id,subject,kind,reason_code,policy_version,notice_key,revokes,proposed_by,state,effective_at,target_type,target_id)
 VALUES(p_case,p_target.subject,'revocation',p_reason,p_target.policy_version,'actionRevoked',p_target.id,p_actor,'effective',clock_timestamp(),
  p_target.target_type,p_target.target_id)
 RETURNING * INTO created;
 PERFORM ts.effect(created);
 RETURN created;
END $$;

-- hide_listing is no longer accepted without a target.
CREATE OR REPLACE FUNCTION ts.action_propose(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_case uuid,p_kind text,p_reason text,p_action_policy text,p_duration_hours int,p_notice text)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE c ts.cases%ROWTYPE; created ts.actions%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_case IS NULL OR p_kind IS NULL
  OR p_kind IN('revocation','hide_listing') THEN
  RAISE EXCEPTION 'invalid_case_command' USING ERRCODE='22023';
 END IF;
 -- A retried command (same event) returns its original action.
 SELECT * INTO created FROM ts.actions WHERE id=(SELECT resource_id FROM audit.log WHERE event_id=p_event AND action='action.decided' LIMIT 1);
 IF FOUND THEN
  IF created.case_id<>p_case OR created.proposed_by<>p_actor OR created.kind<>p_kind OR created.reason_code<>p_reason THEN
   RAISE EXCEPTION 'case_command_conflict' USING ERRCODE='23505';
  END IF;
  RETURN jsonb_build_object('action_id',created.id,'state',created.state);
 END IF;
 SELECT * INTO c FROM ts.cases WHERE id=p_case FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'case_not_found' USING ERRCODE='P0002'; END IF;
 IF c.state<>'open' THEN RAISE EXCEPTION 'case_closed' USING ERRCODE='55000'; END IF;
 IF NOT ts.assigned(p_case,p_actor) OR ts.conflicted(p_case,p_actor) THEN
  RAISE EXCEPTION 'case_not_assigned' USING ERRCODE='42501';
 END IF;
 INSERT INTO ts.actions(case_id,subject,kind,reason_code,policy_version,duration_hours,notice_key,proposed_by,state,effective_at)
 VALUES(p_case,c.subject,p_kind,p_reason,p_action_policy,p_duration_hours,p_notice,p_actor,
  CASE WHEN p_kind IN('ban','suspend') THEN 'proposed' ELSE 'effective' END,
  CASE WHEN p_kind IN('ban','suspend') THEN NULL ELSE clock_timestamp() END)
 RETURNING * INTO created;
 UPDATE ts.cases SET version=version+1 WHERE id=p_case;
 INSERT INTO ts.case_events(case_id,kind,actor,resource) VALUES(p_case,'action_proposed',p_actor,created.id);
 IF created.state='effective' THEN PERFORM ts.effect(created); END IF;
 PERFORM audit.append(p_event,'action.decided',created.id,'case_review',p_policy,p_case);
 RETURN jsonb_build_object('action_id',created.id,'state',created.state);
END $$;

-- The assigned agent hides a listing revision reported in this same case. The
-- target never comes from free input beyond that reported reference.
CREATE FUNCTION ts.listing_hide_propose(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_case uuid,p_target uuid,p_reason text,p_action_policy text,p_notice text)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE c ts.cases%ROWTYPE; created ts.actions%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_case IS NULL OR p_target IS NULL THEN
  RAISE EXCEPTION 'invalid_case_command' USING ERRCODE='22023';
 END IF;
 SELECT * INTO created FROM ts.actions WHERE id=(SELECT resource_id FROM audit.log WHERE event_id=p_event AND action='action.decided' LIMIT 1);
 IF FOUND THEN
  IF created.case_id<>p_case OR created.proposed_by<>p_actor OR created.kind<>'hide_listing'
   OR created.reason_code<>p_reason OR created.target_id IS DISTINCT FROM p_target THEN
   RAISE EXCEPTION 'case_command_conflict' USING ERRCODE='23505';
  END IF;
  RETURN jsonb_build_object('action_id',created.id,'state',created.state);
 END IF;
 SELECT * INTO c FROM ts.cases WHERE id=p_case FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'case_not_found' USING ERRCODE='P0002'; END IF;
 IF c.state<>'open' THEN RAISE EXCEPTION 'case_closed' USING ERRCODE='55000'; END IF;
 IF NOT ts.assigned(p_case,p_actor) OR ts.conflicted(p_case,p_actor) THEN
  RAISE EXCEPTION 'case_not_assigned' USING ERRCODE='42501';
 END IF;
 IF NOT EXISTS(SELECT FROM ts.reports WHERE case_id=p_case AND target_type='listing_revision' AND target_id=p_target) THEN
  RAISE EXCEPTION 'action_target_not_reported' USING ERRCODE='42501';
 END IF;
 INSERT INTO ts.actions(case_id,subject,kind,reason_code,policy_version,notice_key,proposed_by,state,effective_at,target_type,target_id)
 VALUES(p_case,c.subject,'hide_listing',p_reason,p_action_policy,p_notice,p_actor,'effective',clock_timestamp(),'listing_revision',p_target)
 RETURNING * INTO created;
 UPDATE ts.cases SET version=version+1 WHERE id=p_case;
 INSERT INTO ts.case_events(case_id,kind,actor,resource) VALUES(p_case,'action_proposed',p_actor,created.id);
 PERFORM ts.effect(created);
 PERFORM audit.append(p_event,'action.decided',created.id,'case_review',p_policy,p_case);
 RETURN jsonb_build_object('action_id',created.id,'state',created.state);
END $$;
REVOKE ALL ON FUNCTION ts.listing_hide_propose(audit.reference,audit.reference,audit.reference,uuid,uuid,text,text,text) FROM PUBLIC;

-- User: one hold per hide action. The listing is `suspended` while any hold
-- is unreleased; `suspended` is owned by this ledger. Plain references, not
-- foreign keys, so holds never block erasure of a profile.
CREATE TABLE standing.listing_holds (
 action_id uuid PRIMARY KEY REFERENCES standing.ts_effects(action_id),
 subject_id uuid NOT NULL,
 listing_id uuid NOT NULL,
 revision_id uuid NOT NULL,
 held_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 released_by uuid REFERENCES standing.ts_effects(action_id),
 released_at timestamptz,
 CHECK((released_by IS NULL)=(released_at IS NULL))
);
CREATE INDEX listing_hold_active ON standing.listing_holds(listing_id) WHERE released_at IS NULL;

CREATE FUNCTION standing.preserve_listing_hold() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='UPDATE' AND OLD.released_at IS NULL AND NEW.released_at IS NOT NULL
  AND (to_jsonb(NEW)-'released_by'-'released_at')=(to_jsonb(OLD)-'released_by'-'released_at') THEN
  RETURN NEW;
 END IF;
 RAISE EXCEPTION 'listing_hold_history_immutable' USING ERRCODE='55000';
END $$;
CREATE TRIGGER listing_hold_immutable BEFORE UPDATE OR DELETE ON standing.listing_holds
 FOR EACH ROW EXECUTE FUNCTION standing.preserve_listing_hold();

-- Same contract as V058, plus the optional target. Exact historical replays
-- are still acknowledged before any validation of new commands.
CREATE OR REPLACE FUNCTION standing.apply_ts_effect(p_event uuid,p_payload jsonb,p_policy uuid)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE e standing.ts_effects%ROWTYPE; prior standing.ts_effects%ROWTYPE; target standing.ts_effects%ROWTYPE; principal uuid;
 keys text[]; revision uuid; hold standing.listing_holds%ROWTYPE; listing uuid; listing_owner uuid; changed boolean:=false;
 base constant text[]:=ARRAY['action_id','case_id','duration_hours','effective_at','kind','notice_key','policy_version','reason_code','revokes','subject'];
BEGIN
 IF p_event IS NULL OR p_policy IS NULL OR jsonb_typeof(p_payload)<>'object' THEN
  RAISE EXCEPTION 'invalid_ts_effect' USING ERRCODE='22023';
 END IF;
 keys:=(SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_payload) k);
 IF keys IS DISTINCT FROM base AND keys IS DISTINCT FROM base||'target'::text THEN
  RAISE EXCEPTION 'invalid_ts_effect' USING ERRCODE='22023';
 END IF;
 BEGIN
  e.action_id:=(p_payload->>'action_id')::uuid; e.case_id:=(p_payload->>'case_id')::uuid;
  principal:=(p_payload->>'subject')::uuid; e.kind:=p_payload->>'kind';
  e.revokes:=(p_payload->>'revokes')::uuid; e.policy_version:=p_payload->>'policy_version';
  e.starts_at:=(p_payload->>'effective_at')::timestamptz;
  e.ends_at:=CASE WHEN p_payload->>'duration_hours' IS NULL THEN NULL
   ELSE e.starts_at+make_interval(hours=>(p_payload->>'duration_hours')::int) END;
  revision:=(p_payload#>>'{target,id}')::uuid;
 EXCEPTION WHEN others THEN
  RAISE EXCEPTION 'invalid_ts_effect' USING ERRCODE='22023';
 END;
 IF e.action_id IS NULL OR principal IS NULL OR e.case_id IS NULL OR e.starts_at IS NULL
  OR '00000000-0000-0000-0000-000000000000'::uuid IN(p_event,p_policy,e.action_id,e.case_id,principal) THEN
  RAISE EXCEPTION 'invalid_ts_effect' USING ERRCODE='22023';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('ts-effect-action:'||e.action_id::text,0));
 SELECT effect.* INTO prior FROM standing.ts_effects effect
 JOIN standing.ts_effect_deliveries delivery ON delivery.action_id=effect.action_id
 WHERE delivery.event_id=p_event;
 IF NOT FOUND THEN
  SELECT * INTO prior FROM standing.ts_effects WHERE action_id=e.action_id;
 END IF;
 IF FOUND THEN
  IF prior.action_id<>e.action_id OR NOT EXISTS (
   SELECT 1 FROM standing.ts_effect_receipts receipt
   WHERE receipt.action_id=prior.action_id AND receipt.payload=p_payload
  ) THEN
   RAISE EXCEPTION 'ts_effect_conflict' USING ERRCODE='23505';
  END IF;
  PERFORM standing.record_ts_effect_delivery(p_event,prior.action_id);
  RETURN jsonb_build_object('action_id',prior.action_id,'duplicate',true);
 END IF;
 -- These bounds match the producer's typed action fields, not a new legal
 -- retention or sanction policy. Historical acknowledgements above stay exact.
 IF octet_length(p_payload::text)>4096
  OR jsonb_typeof(p_payload->'subject')<>'string' OR p_payload->>'subject'<>principal::text
  OR jsonb_typeof(p_payload->'action_id')<>'string' OR p_payload->>'action_id'<>e.action_id::text
  OR jsonb_typeof(p_payload->'case_id')<>'string' OR p_payload->>'case_id'<>e.case_id::text
  OR jsonb_typeof(p_payload->'kind')<>'string'
  OR e.kind NOT IN('warning','hide_listing','restrict_publish','restrict_booking','suspend','ban','revocation')
  OR jsonb_typeof(p_payload->'reason_code')<>'string' OR p_payload->>'reason_code' !~ '^[a-z][a-z0-9_]{1,63}$'
  OR jsonb_typeof(p_payload->'policy_version')<>'string' OR e.policy_version !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
  OR jsonb_typeof(p_payload->'notice_key')<>'string' OR p_payload->>'notice_key' !~ '^[a-zA-Z][a-zA-Z0-9]{1,127}$'
  OR jsonb_typeof(p_payload->'effective_at')<>'string' OR NOT isfinite(e.starts_at)
  OR p_payload->>'effective_at' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,6})?Z$'
  OR (p_payload->'duration_hours'<>'null'::jsonb AND
      (jsonb_typeof(p_payload->'duration_hours')<>'number'
       OR p_payload->>'duration_hours' !~ '^[1-9][0-9]{0,4}$'
       OR (p_payload->>'duration_hours')::int>87600))
  OR (e.kind='revocation')<>(e.revokes IS NOT NULL)
  OR (p_payload->'revokes'<>'null'::jsonb AND
      (jsonb_typeof(p_payload->'revokes')<>'string'
       OR e.revokes='00000000-0000-0000-0000-000000000000'::uuid
       OR p_payload->>'revokes'<>e.revokes::text))
  OR (e.kind='revocation' AND p_payload->'duration_hours'<>'null'::jsonb)
  -- Target: required by hide_listing, optional on a revocation, absent elsewhere.
  OR (e.kind='hide_listing' AND (revision IS NULL OR p_payload->'duration_hours'<>'null'::jsonb))
  OR (p_payload ? 'target' AND (
      e.kind NOT IN('hide_listing','revocation')
      OR jsonb_typeof(p_payload->'target')<>'object'
      OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_payload->'target') k) IS DISTINCT FROM ARRAY['id','type']
      OR jsonb_typeof(p_payload#>'{target,type}')<>'string' OR p_payload#>>'{target,type}'<>'listing_revision'
      OR jsonb_typeof(p_payload#>'{target,id}')<>'string' OR p_payload#>>'{target,id}'<>revision::text
      OR revision='00000000-0000-0000-0000-000000000000'::uuid)) THEN
  RAISE EXCEPTION 'invalid_ts_effect' USING ERRCODE='22023';
 END IF;
 -- New actions use the realm principal only. Never try usuario.id as an
 -- alternative: it may identify an entirely different account.
 SELECT id INTO e.subject_id FROM public.usuario WHERE keycloak_id=principal::text FOR KEY SHARE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'ts_effect_subject_missing' USING ERRCODE='P0002';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('ts-effect:'||e.subject_id::text,0));
 IF e.kind='revocation' THEN
  SELECT * INTO target FROM standing.ts_effects WHERE action_id=e.revokes FOR UPDATE;
  IF NOT FOUND OR target.subject_id<>e.subject_id THEN
   -- Out-of-order delivery: the consumer retries until the target arrives.
   RAISE EXCEPTION 'ts_effect_target_missing' USING ERRCODE='40001';
  END IF;
  SELECT * INTO hold FROM standing.listing_holds WHERE action_id=e.revokes FOR UPDATE;
  -- A revocation repeats the target of a hold it releases, and only that.
  IF (target.kind='hide_listing' AND revision IS NULL AND FOUND)
   OR (revision IS NOT NULL AND (NOT FOUND OR hold.revision_id<>revision)) THEN
   RAISE EXCEPTION 'invalid_ts_effect' USING ERRCODE='22023';
  END IF;
  e.ends_at:=NULL;
 ELSIF e.kind='hide_listing' THEN
  -- The listing owner must be the subject of the action.
  SELECT l.id,cp.usuario_id INTO listing,listing_owner FROM public.listing_revisions r
  JOIN public.listings l ON l.id=r.listing_id JOIN public.compa_perfil cp ON cp.id=l.compa_id
  WHERE r.id=revision FOR NO KEY UPDATE OF l;
  IF NOT FOUND THEN
   RAISE EXCEPTION 'ts_effect_listing_missing' USING ERRCODE='P0002';
  END IF;
  IF listing_owner<>e.subject_id THEN
   RAISE EXCEPTION 'ts_effect_listing_mismatch' USING ERRCODE='22023';
  END IF;
 END IF;
 e.received_event:=p_event;
 INSERT INTO standing.ts_effects(action_id,received_event,subject_id,case_id,kind,revokes,policy_version,starts_at,ends_at)
 VALUES(e.action_id,e.received_event,e.subject_id,e.case_id,e.kind,e.revokes,e.policy_version,e.starts_at,e.ends_at);
 INSERT INTO standing.ts_effect_receipts(action_id,payload,subject_namespace) VALUES(e.action_id,p_payload,'keycloak_sub');
 PERFORM standing.record_ts_effect_delivery(p_event,e.action_id);
 IF e.kind='revocation' AND target.revoked_at IS NULL THEN
  UPDATE standing.ts_effects SET revoked_at=clock_timestamp() WHERE action_id=e.revokes;
 END IF;
 IF e.kind='hide_listing' THEN
  INSERT INTO standing.listing_holds(action_id,subject_id,listing_id,revision_id) VALUES(e.action_id,e.subject_id,listing,revision);
  UPDATE public.listings SET state='suspended',version=version+1
  WHERE id=listing AND state IN('published','unpublished');
  changed:=FOUND;
  RETURN jsonb_build_object('action_id',e.action_id,'duplicate',false,'changed',changed);
 END IF;
 IF e.kind='revocation' AND hold.action_id IS NOT NULL AND hold.released_at IS NULL THEN
  UPDATE standing.listing_holds SET released_by=e.action_id,released_at=clock_timestamp() WHERE action_id=hold.action_id;
  IF NOT EXISTS(SELECT FROM standing.listing_holds WHERE listing_id=hold.listing_id AND released_at IS NULL) THEN
   UPDATE public.listings SET state=CASE WHEN published_revision_id IS NULL THEN 'unpublished' ELSE 'published' END,
    version=version+1 WHERE id=hold.listing_id AND state='suspended';
  END IF;
 END IF;
 IF e.kind='warning' THEN
  RETURN jsonb_build_object('action_id',e.action_id,'duplicate',false,'changed',false);
 END IF;
 RETURN jsonb_build_object('action_id',e.action_id,'duplicate',false)
  || standing.derive_ts_standing(p_event,e.subject_id,p_policy,e.case_id);
END $$;

REVOKE ALL ON standing.listing_holds FROM PUBLIC;
REVOKE ALL ON FUNCTION standing.preserve_listing_hold() FROM PUBLIC;
GRANT SELECT ON standing.listing_holds TO rac_backup;
