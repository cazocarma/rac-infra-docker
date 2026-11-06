-- T&S subjects and staff actors share the configured realm's canonical UUID
-- sub. User alone resolves that principal to its independently generated ID.
-- Mark historical receipts without rewriting their body or claimed capture.
SET LOCAL lock_timeout='2s';
ALTER TABLE standing.ts_effect_receipts ADD COLUMN subject_namespace text NOT NULL DEFAULT 'user_id'
 CHECK(subject_namespace IN('user_id','keycloak_sub'));
ALTER TABLE standing.ts_effect_receipts ALTER COLUMN subject_namespace SET DEFAULT 'keycloak_sub';

-- Exact historical replays acknowledge only the already recorded action. New
-- actions must resolve a Keycloak sub; no legacy-ID write path is retained.
CREATE OR REPLACE FUNCTION standing.apply_ts_effect(p_event uuid,p_payload jsonb,p_policy uuid)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE e standing.ts_effects%ROWTYPE; prior standing.ts_effects%ROWTYPE; target standing.ts_effects%ROWTYPE; principal uuid;
BEGIN
 IF p_event IS NULL OR p_policy IS NULL OR jsonb_typeof(p_payload)<>'object'
  OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_payload) k)<>ARRAY['action_id','case_id','duration_hours','effective_at','kind','notice_key','policy_version','reason_code','revokes','subject'] THEN
  RAISE EXCEPTION 'invalid_ts_effect' USING ERRCODE='22023';
 END IF;
 BEGIN
  e.action_id:=(p_payload->>'action_id')::uuid; e.case_id:=(p_payload->>'case_id')::uuid;
  principal:=(p_payload->>'subject')::uuid; e.kind:=p_payload->>'kind';
  e.revokes:=(p_payload->>'revokes')::uuid; e.policy_version:=p_payload->>'policy_version';
  e.starts_at:=(p_payload->>'effective_at')::timestamptz;
  e.ends_at:=CASE WHEN p_payload->>'duration_hours' IS NULL THEN NULL
   ELSE e.starts_at+make_interval(hours=>(p_payload->>'duration_hours')::int) END;
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
  OR (e.kind='revocation' AND p_payload->'duration_hours'<>'null'::jsonb) THEN
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
  e.ends_at:=NULL;
 END IF;
 e.received_event:=p_event;
 INSERT INTO standing.ts_effects(action_id,received_event,subject_id,case_id,kind,revokes,policy_version,starts_at,ends_at)
 VALUES(e.action_id,e.received_event,e.subject_id,e.case_id,e.kind,e.revokes,e.policy_version,e.starts_at,e.ends_at);
 INSERT INTO standing.ts_effect_receipts(action_id,payload,subject_namespace) VALUES(e.action_id,p_payload,'keycloak_sub');
 PERFORM standing.record_ts_effect_delivery(p_event,e.action_id);
 IF e.kind='revocation' AND target.revoked_at IS NULL THEN
  UPDATE standing.ts_effects SET revoked_at=clock_timestamp() WHERE action_id=e.revokes;
 END IF;
 IF e.kind IN('warning','hide_listing') THEN
  RETURN jsonb_build_object('action_id',e.action_id,'duplicate',false,'changed',false);
 END IF;
 RETURN jsonb_build_object('action_id',e.action_id,'duplicate',false)
  || standing.derive_ts_standing(p_event,e.subject_id,p_policy,e.case_id);
END $$;
