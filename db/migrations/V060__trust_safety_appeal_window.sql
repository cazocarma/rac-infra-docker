-- P11 appeal window (D07, approved direction): the affected person may file an
-- appeal within thirty days of the action becoming effective. This is a filing
-- deadline, not a response SLA; nothing here promises when an appeal is decided.
-- The window is a single reviewed constant so notices and intake read the same
-- value. A replay of an appeal filed in time stays idempotent after the window.

CREATE FUNCTION ts.appeal_window() RETURNS interval
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$ SELECT interval '30 days' $$;
REVOKE ALL ON FUNCTION ts.appeal_window() FROM PUBLIC;

CREATE OR REPLACE FUNCTION ts.appeal_submit(p_event audit.reference,p_appellant audit.reference,p_policy audit.reference,
 p_action uuid,p_statement uuid)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE a ts.actions%ROWTYPE; prior ts.appeals%ROWTYPE; created uuid; deadline text;
BEGIN
 IF p_event IS NULL OR p_appellant IS NULL OR p_policy IS NULL OR p_action IS NULL THEN
  RAISE EXCEPTION 'invalid_appeal' USING ERRCODE='22023';
 END IF;
 SELECT * INTO a FROM ts.actions WHERE id=p_action FOR SHARE;
 IF NOT FOUND OR a.subject<>p_appellant OR a.kind='revocation' OR a.state<>'effective' THEN
  RAISE EXCEPTION 'appeal_not_available' USING ERRCODE='42501';
 END IF;
 IF p_statement IS NOT NULL AND NOT EXISTS(SELECT FROM ts.evidence_manifests WHERE id=p_statement AND state='stored' AND purpose='appeal') THEN
  RAISE EXCEPTION 'invalid_appeal' USING ERRCODE='22023';
 END IF;
 deadline:=to_char((a.effective_at + ts.appeal_window()) AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"');
 PERFORM pg_advisory_xact_lock(hashtextextended('appeal:'||p_action::text,0));
 SELECT * INTO prior FROM ts.appeals WHERE action_id=p_action;
 IF FOUND THEN RETURN jsonb_build_object('appeal_id',prior.id,'duplicate',true,'deadline',deadline); END IF;
 IF clock_timestamp() > a.effective_at + ts.appeal_window() THEN
  RAISE EXCEPTION 'appeal_window_closed' USING ERRCODE='55000';
 END IF;
 INSERT INTO ts.appeals(action_id,appellant,statement_evidence) VALUES(p_action,p_appellant,p_statement) RETURNING id INTO created;
 INSERT INTO ts.case_events(case_id,kind,actor,resource) VALUES(a.case_id,'appeal_submitted',p_appellant,created);
 RETURN jsonb_build_object('appeal_id',created,'duplicate',false,'deadline',deadline);
END $$;
