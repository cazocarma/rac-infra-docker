-- Preserve the complete received command, not just the effect's projection.
-- A reused event must never acknowledge another action, and an action replay
-- must be semantically identical even when its transport event ID changes.
SET LOCAL lock_timeout='2s';

CREATE TABLE standing.ts_effect_receipts (
 action_id uuid PRIMARY KEY REFERENCES standing.ts_effects(action_id),
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=4096)
);

-- One-time upgrade from the immutable source outbox. Never manufacture a
-- receipt from the lossy standing projection. A missing/conflicting source
-- stops the migration for explicit reconciliation, without altering effects.
INSERT INTO standing.ts_effect_receipts(action_id,payload)
 SELECT e.action_id,o.payload FROM standing.ts_effects e JOIN ts.outbox o
 ON o.event_id=e.received_event AND o.event_type='ts.action.effective.v1'
 WHERE o.payload->>'action_id'=e.action_id::text
 AND o.payload->>'subject'=e.subject_id::text
 AND o.payload->>'case_id'=e.case_id::text
 AND o.payload->>'kind'=e.kind
 AND (o.payload->>'revokes')::uuid IS NOT DISTINCT FROM e.revokes
 AND o.payload->>'policy_version'=e.policy_version
 AND (o.payload->>'effective_at')::timestamptz=e.starts_at
 AND (CASE WHEN o.payload->>'duration_hours' IS NULL THEN NULL
      ELSE e.starts_at+make_interval(hours=>(o.payload->>'duration_hours')::int) END)
     IS NOT DISTINCT FROM e.ends_at;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM standing.ts_effects e LEFT JOIN standing.ts_effect_receipts r
  ON r.action_id=e.action_id WHERE r.action_id IS NULL) THEN
  RAISE EXCEPTION 'ts_effect_receipt_reconciliation_required' USING ERRCODE='55000';
 END IF;
END $$;

CREATE TABLE standing.ts_effect_deliveries (
 event_id uuid PRIMARY KEY,
 action_id uuid NOT NULL REFERENCES standing.ts_effect_receipts(action_id)
);
CREATE INDEX ts_effect_delivery_action ON standing.ts_effect_deliveries(action_id);
INSERT INTO standing.ts_effect_deliveries(event_id,action_id)
 SELECT received_event,action_id FROM standing.ts_effects;

CREATE FUNCTION standing.preserve_ts_effect_receipt() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN
 RAISE EXCEPTION 'ts_effect_receipt_immutable' USING ERRCODE='55000';
END $$;
CREATE TRIGGER ts_effect_receipt_immutable BEFORE UPDATE OR DELETE ON standing.ts_effect_receipts
 FOR EACH ROW EXECUTE FUNCTION standing.preserve_ts_effect_receipt();
CREATE TRIGGER ts_effect_delivery_immutable BEFORE UPDATE OR DELETE ON standing.ts_effect_deliveries
 FOR EACH ROW EXECUTE FUNCTION standing.preserve_ts_effect_receipt();
REVOKE ALL ON standing.ts_effect_receipts,standing.ts_effect_deliveries FROM PUBLIC;
REVOKE ALL ON FUNCTION standing.preserve_ts_effect_receipt() FROM PUBLIC;
GRANT SELECT ON standing.ts_effect_receipts,standing.ts_effect_deliveries TO rac_backup;

-- Record every acknowledged delivery ID, including aliases for an identical
-- action. A concurrent collision cannot silently retarget an existing event.
CREATE FUNCTION standing.record_ts_effect_delivery(p_event uuid,p_action uuid) RETURNS void
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN
 INSERT INTO standing.ts_effect_deliveries(event_id,action_id) VALUES(p_event,p_action)
 ON CONFLICT(event_id) DO NOTHING;
 IF NOT EXISTS(SELECT 1 FROM standing.ts_effect_deliveries WHERE event_id=p_event AND action_id=p_action) THEN
  RAISE EXCEPTION 'ts_effect_conflict' USING ERRCODE='23505';
 END IF;
END $$;
REVOKE ALL ON FUNCTION standing.record_ts_effect_delivery(uuid,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION standing.apply_ts_effect(p_event uuid,p_payload jsonb,p_policy uuid)
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
 INSERT INTO standing.ts_effect_receipts(action_id,payload) VALUES(e.action_id,p_payload);
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
