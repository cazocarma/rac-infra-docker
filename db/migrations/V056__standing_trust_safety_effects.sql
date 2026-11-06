-- User-owned ledger of effective T&S actions (ts.action.effective.v1). The
-- user owner, not T&S, derives standing from the active effects and applies
-- it through standing.change_account, so its outbox, session effects and
-- audit stay the single path. Rights capabilities are never restricted.
SET LOCAL lock_timeout='2s';

CREATE TABLE standing.ts_effects (
 action_id uuid PRIMARY KEY,
 received_event uuid NOT NULL UNIQUE,
 subject_id uuid NOT NULL REFERENCES standing.account(subject_id),
 case_id uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN('warning','hide_listing','restrict_publish','restrict_booking','suspend','ban','revocation')),
 revokes uuid REFERENCES standing.ts_effects(action_id),
 policy_version text NOT NULL CHECK(policy_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
 starts_at timestamptz NOT NULL CHECK(isfinite(starts_at)),
 ends_at timestamptz CHECK(ends_at IS NULL OR (isfinite(ends_at) AND ends_at>starts_at)),
 revoked_at timestamptz,
 received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK((kind='revocation')=(revokes IS NOT NULL)),
 CHECK(kind<>'revocation' OR ends_at IS NULL)
);
CREATE INDEX ts_effect_active ON standing.ts_effects(subject_id) WHERE revoked_at IS NULL AND kind<>'revocation';

CREATE FUNCTION standing.preserve_ts_effect() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
  IF OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL
   AND (to_jsonb(NEW)-'revoked_at')=(to_jsonb(OLD)-'revoked_at') THEN
   RETURN NEW;
  END IF;
 END IF;
 RAISE EXCEPTION 'ts_effect_history_immutable' USING ERRCODE='55000';
END $$;
CREATE TRIGGER ts_effect_immutable BEFORE UPDATE OR DELETE ON standing.ts_effects
 FOR EACH ROW EXECUTE FUNCTION standing.preserve_ts_effect();

-- Recomputes standing from active effects and applies it only when it
-- differs from the current account state.
CREATE FUNCTION standing.derive_ts_standing(p_event uuid,p_subject uuid,p_policy uuid,p_case uuid)
 RETURNS jsonb LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE a standing.account%ROWTYPE; now_at timestamptz:=clock_timestamp(); target text; wanted jsonb; current jsonb;
BEGIN
 SELECT * INTO a FROM standing.account WHERE subject_id=p_subject FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'standing_subject_missing' USING ERRCODE='P0002'; END IF;
 SELECT CASE
   WHEN bool_or(kind='ban') THEN 'banned'
   WHEN bool_or(kind='suspend') THEN 'suspended'
   WHEN bool_or(kind IN('restrict_publish','restrict_booking')) THEN 'restricted'
   ELSE 'active' END
 INTO target FROM standing.ts_effects
 WHERE subject_id=p_subject AND revoked_at IS NULL AND kind<>'revocation' AND starts_at<=now_at AND (ends_at IS NULL OR ends_at>now_at);
 target:=COALESCE(target,'active');
 SELECT COALESCE(jsonb_agg(jsonb_build_object('capability',c.capability,
   'starts_at',to_char(e.starts_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
   'ends_at',CASE WHEN e.ends_at IS NULL THEN NULL ELSE to_char(e.ends_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') END)
   ORDER BY c.capability,e.starts_at),'[]')
 INTO wanted FROM standing.ts_effects e
 JOIN (VALUES('restrict_publish','publish_listing'),('restrict_booking','request_booking'),('restrict_booking','accept_booking')) c(kind,capability)
  ON c.kind=e.kind
 WHERE e.subject_id=p_subject AND e.revoked_at IS NULL AND (e.ends_at IS NULL OR e.ends_at>now_at);
 SELECT COALESCE(jsonb_agg(jsonb_build_object('capability',capability,
   'starts_at',to_char(starts_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
   'ends_at',CASE WHEN ends_at IS NULL THEN NULL ELSE to_char(ends_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') END)
   ORDER BY capability,starts_at),'[]')
 INTO current FROM standing.restriction WHERE subject_id=p_subject AND (ends_at IS NULL OR ends_at>now_at);
 IF a.status=target AND current=wanted THEN
  RETURN jsonb_build_object('subject_id',p_subject,'status',a.status,'changed',false);
 END IF;
 PERFORM standing.change_account(p_event,p_subject,a.version,target,wanted,p_policy,p_case);
 RETURN jsonb_build_object('subject_id',p_subject,'status',target,'changed',true);
END $$;

-- Applies one delivered event exactly once. Replays of the same event return
-- the recorded outcome; another event for an already recorded action is a
-- duplicate delivery and changes nothing.
CREATE FUNCTION standing.apply_ts_effect(p_event uuid,p_payload jsonb,p_policy uuid)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE e standing.ts_effects%ROWTYPE; prior standing.ts_effects%ROWTYPE; target standing.ts_effects%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_policy IS NULL OR jsonb_typeof(p_payload)<>'object'
  OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_payload) k)<>ARRAY['action_id','case_id','duration_hours','effective_at','kind','notice_key','policy_version','reason_code','revokes','subject'] THEN
  RAISE EXCEPTION 'invalid_ts_effect' USING ERRCODE='22023';
 END IF;
 BEGIN
  e.action_id:=(p_payload->>'action_id')::uuid; e.case_id:=(p_payload->>'case_id')::uuid;
  e.subject_id:=(p_payload->>'subject')::uuid; e.kind:=p_payload->>'kind';
  e.revokes:=(p_payload->>'revokes')::uuid; e.policy_version:=p_payload->>'policy_version';
  e.starts_at:=(p_payload->>'effective_at')::timestamptz;
  e.ends_at:=CASE WHEN p_payload->>'duration_hours' IS NULL THEN NULL
   ELSE e.starts_at+make_interval(hours=>(p_payload->>'duration_hours')::int) END;
 EXCEPTION WHEN others THEN
  RAISE EXCEPTION 'invalid_ts_effect' USING ERRCODE='22023';
 END;
 IF e.action_id IS NULL OR e.subject_id IS NULL OR e.case_id IS NULL OR e.starts_at IS NULL THEN
  RAISE EXCEPTION 'invalid_ts_effect' USING ERRCODE='22023';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('ts-effect:'||e.subject_id::text,0));
 SELECT * INTO prior FROM standing.ts_effects WHERE action_id=e.action_id OR received_event=p_event LIMIT 1;
 IF FOUND THEN
  IF prior.action_id<>e.action_id OR prior.subject_id<>e.subject_id OR prior.kind<>e.kind THEN
   RAISE EXCEPTION 'ts_effect_conflict' USING ERRCODE='23505';
  END IF;
  RETURN jsonb_build_object('action_id',prior.action_id,'duplicate',true);
 END IF;
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
 IF e.kind='revocation' AND target.revoked_at IS NULL THEN
  UPDATE standing.ts_effects SET revoked_at=clock_timestamp() WHERE action_id=e.revokes;
 END IF;
 IF e.kind IN('warning','hide_listing') THEN
  RETURN jsonb_build_object('action_id',e.action_id,'duplicate',false,'changed',false);
 END IF;
 RETURN jsonb_build_object('action_id',e.action_id,'duplicate',false)
  || standing.derive_ts_standing(p_event,e.subject_id,p_policy,e.case_id);
END $$;

-- Periodic refresh once timed restrictions or suspensions expire.
CREATE FUNCTION standing.refresh_ts_standing(p_event uuid,p_subject uuid,p_policy uuid)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE latest uuid;
BEGIN
 IF p_event IS NULL OR p_subject IS NULL OR p_policy IS NULL THEN
  RAISE EXCEPTION 'invalid_ts_effect' USING ERRCODE='22023';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('ts-effect:'||p_subject::text,0));
 SELECT case_id INTO latest FROM standing.ts_effects WHERE subject_id=p_subject ORDER BY received_at DESC LIMIT 1;
 IF NOT FOUND THEN RETURN jsonb_build_object('subject_id',p_subject,'changed',false); END IF;
 RETURN standing.derive_ts_standing(p_event,p_subject,p_policy,latest);
END $$;

REVOKE ALL ON standing.ts_effects FROM PUBLIC;
REVOKE ALL ON FUNCTION standing.derive_ts_standing(uuid,uuid,uuid,uuid),
 standing.apply_ts_effect(uuid,jsonb,uuid),standing.refresh_ts_standing(uuid,uuid,uuid) FROM PUBLIC;
GRANT SELECT ON standing.ts_effects TO rac_backup;
-- No consumer grant: the effects consumer login is provisioned explicitly.
