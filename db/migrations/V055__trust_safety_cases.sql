-- P11 unified reports, cases, actions and appeals owned by T&S (ADR-003).
-- Effects on other owners leave through ts.outbox as versioned commands; this
-- schema never writes standing, listings, bookings or chat tables. SLA, the
-- appeal window and automatic protections (D06/D07) are not encoded here.
SET LOCAL lock_timeout='2s';

ALTER TABLE audit.log DROP CONSTRAINT log_action_check;
ALTER TABLE audit.log ADD CONSTRAINT log_action_check CHECK(action IN
 ('evidence.accessed','standing.changed','policy.published','listing.reviewed',
  'document.drafted','document.reviewed','document.published','evidence.captured',
  'report.received','case.assigned','action.decided','appeal.decided'));

CREATE OR REPLACE FUNCTION audit.append(
 p_event uuid, p_action text, p_resource uuid, p_purpose text,
 p_policy uuid, p_case uuid DEFAULT NULL
) RETURNS audit.log LANGUAGE plpgsql SECURITY DEFINER
 SET search_path=pg_catalog AS $$
DECLARE
 principal audit.writer_principals%ROWTYPE;
 head audit.chain_heads%ROWTYPE;
 result audit.log%ROWTYPE;
 existing audit.log%ROWTYPE;
 payload text;
BEGIN
 SELECT * INTO principal FROM audit.writer_principals WHERE database_role=session_user;
 IF NOT FOUND THEN RAISE EXCEPTION 'audit_writer_not_provisioned' USING ERRCODE='42501'; END IF;
 IF p_event IS NULL OR p_event='00000000-0000-0000-0000-000000000000'::uuid
 OR p_resource IS NULL OR p_resource='00000000-0000-0000-0000-000000000000'::uuid
 OR p_policy IS NULL OR p_policy='00000000-0000-0000-0000-000000000000'::uuid
 OR p_case='00000000-0000-0000-0000-000000000000'::uuid
 OR p_action IS NULL OR p_action NOT IN ('evidence.accessed','standing.changed','policy.published','listing.reviewed','document.drafted','document.reviewed','document.published','evidence.captured','report.received','case.assigned','action.decided','appeal.decided')
 OR p_purpose IS NULL OR p_purpose NOT IN ('operational','case_review','legal_request','security') THEN
  RAISE EXCEPTION 'invalid_audit_metadata' USING ERRCODE='22023';
 END IF;
 SELECT * INTO STRICT head FROM audit.chain_heads WHERE chain_id=principal.chain_id FOR UPDATE;
 SELECT * INTO existing FROM audit.log WHERE chain_id=head.chain_id AND event_id=p_event;
 IF FOUND THEN
  IF existing.actor_id<>principal.actor_id OR existing.action<>p_action
   OR existing.resource_id<>p_resource OR existing.purpose<>p_purpose
   OR existing.policy_version<>p_policy OR existing.case_id IS DISTINCT FROM p_case THEN
   RAISE EXCEPTION 'audit_event_conflict' USING ERRCODE='23505';
  END IF;
  RETURN existing;
 END IF;
 result.chain_id:=head.chain_id; result.sequence:=head.sequence+1;
 result.version:=1; result.event_id:=p_event; result.occurred_at:=clock_timestamp();
 result.actor_id:=principal.actor_id; result.action:=p_action;
 result.resource_id:=p_resource; result.purpose:=p_purpose;
 result.policy_version:=p_policy; result.case_id:=p_case;
 result.previous_hash:=head.hash;
 payload:=audit.canonical_v1(result.chain_id,result.sequence,result.event_id,result.occurred_at,
 result.actor_id,result.action,result.resource_id,result.purpose,result.policy_version,
 coalesce(result.case_id,'00000000-0000-0000-0000-000000000000'::uuid),result.previous_hash);
 result.hash:=encode(public.digest(convert_to(payload,'UTF8'),'sha256'),'hex');
 INSERT INTO audit.log SELECT result.*;
 UPDATE audit.chain_heads SET sequence=result.sequence,hash=result.hash WHERE chain_id=result.chain_id;
 RETURN result;
END $$;

CREATE FUNCTION ts.severity(p_category text) RETURNS text
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT CASE p_category
  WHEN 'minors' THEN 'P0' WHEN 'imminent_danger' THEN 'P0'
  WHEN 'drugs' THEN 'P1' WHEN 'sexual_services' THEN 'P1' WHEN 'violence' THEN 'P1' WHEN 'weapons' THEN 'P1'
  WHEN 'fraud' THEN 'P2' WHEN 'harassment' THEN 'P2' WHEN 'impersonation' THEN 'P2' WHEN 'off_platform' THEN 'P2'
  WHEN 'other' THEN 'P3' END $$;

CREATE TABLE ts.cases (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 subject audit.reference NOT NULL,
 severity text NOT NULL CHECK(severity IN('P0','P1','P2','P3')),
 state text NOT NULL DEFAULT 'open' CHECK(state IN('open','closed')),
 opened_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 closed_at timestamptz,
 version bigint NOT NULL DEFAULT 1 CHECK(version>0),
 CHECK((state='open')=(closed_at IS NULL))
);
CREATE INDEX case_open_by_subject ON ts.cases(subject,severity) WHERE state='open';

CREATE TABLE ts.reports (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 reporter audit.reference NOT NULL,
 target_type text NOT NULL CHECK(target_type IN('account','listing_revision','photo','review','conversation','booking')),
 target_id uuid NOT NULL,
 subject audit.reference NOT NULL,
 category text NOT NULL CHECK(ts.severity(category) IS NOT NULL),
 description_evidence uuid REFERENCES ts.evidence_manifests(id),
 case_id uuid NOT NULL REFERENCES ts.cases(id),
 state text NOT NULL DEFAULT 'open' CHECK(state IN('open','closed')),
 received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(reporter<>subject)
);
-- One open report per reporter and target, including concurrent retries.
CREATE UNIQUE INDEX report_open_once ON ts.reports(reporter,target_type,target_id) WHERE state='open';
CREATE INDEX report_by_case ON ts.reports(case_id);

CREATE TABLE ts.case_assignments (
 id bigserial PRIMARY KEY,
 case_id uuid NOT NULL REFERENCES ts.cases(id),
 assignee audit.reference NOT NULL,
 assigned_by audit.reference NOT NULL,
 assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 released_at timestamptz
);
CREATE UNIQUE INDEX case_assignment_active ON ts.case_assignments(case_id) WHERE released_at IS NULL;

CREATE TABLE ts.case_events (
 id bigserial PRIMARY KEY,
 case_id uuid NOT NULL REFERENCES ts.cases(id),
 kind text NOT NULL CHECK(kind IN('opened','report_linked','assigned','action_proposed','action_effective','action_revoked','appeal_submitted','appeal_decided','closed')),
 actor audit.reference NOT NULL,
 resource uuid,
 occurred_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE ts.actions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 case_id uuid NOT NULL REFERENCES ts.cases(id),
 subject audit.reference NOT NULL,
 kind text NOT NULL CHECK(kind IN('warning','hide_listing','restrict_publish','restrict_booking','suspend','ban','revocation')),
 reason_code text NOT NULL CHECK(reason_code ~ '^[a-z][a-z0-9_]{1,63}$'),
 policy_version text NOT NULL CHECK(policy_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
 duration_hours int CHECK(duration_hours IS NULL OR duration_hours BETWEEN 1 AND 87600),
 notice_key text NOT NULL CHECK(notice_key ~ '^[a-zA-Z][a-zA-Z0-9]{1,127}$'),
 revokes uuid REFERENCES ts.actions(id),
 proposed_by audit.reference NOT NULL,
 approved_by audit.reference,
 state text NOT NULL CHECK(state IN('proposed','effective')),
 proposed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 effective_at timestamptz,
 CHECK(approved_by IS NULL OR approved_by<>proposed_by),
 CHECK(proposed_by<>subject AND (approved_by IS NULL OR approved_by<>subject)),
 -- Four eyes: a ban or suspension is effective only with a distinct approver.
 CHECK(kind NOT IN('ban','suspend') OR state='proposed' OR approved_by IS NOT NULL),
 CHECK((state='effective')=(effective_at IS NOT NULL)),
 CHECK((kind='revocation')=(revokes IS NOT NULL))
);
CREATE UNIQUE INDEX action_revoked_once ON ts.actions(revokes) WHERE revokes IS NOT NULL;

CREATE TABLE ts.appeals (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 action_id uuid NOT NULL UNIQUE REFERENCES ts.actions(id),
 appellant audit.reference NOT NULL,
 statement_evidence uuid REFERENCES ts.evidence_manifests(id),
 submitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 decided_by audit.reference,
 outcome text CHECK(outcome IN('upheld','overturned')),
 decided_at timestamptz,
 CHECK((decided_by IS NULL)=(outcome IS NULL) AND (outcome IS NULL)=(decided_at IS NULL)),
 CHECK(decided_by IS NULL OR decided_by<>appellant)
);

CREATE TABLE ts.outbox (
 id bigserial PRIMARY KEY,
 event_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
 event_type text NOT NULL CHECK(event_type IN('ts.action.effective.v1')),
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object' AND octet_length(payload::text)<=4096),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION ts.preserve_case_history() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 -- Nested by table: PL/pgSQL does not short-circuit record field lookups.
 IF TG_OP='UPDATE' THEN
  IF TG_TABLE_NAME='actions' THEN
   IF OLD.state='proposed' AND NEW.state='effective'
    AND (to_jsonb(NEW)-'state'-'approved_by'-'effective_at')=(to_jsonb(OLD)-'state'-'approved_by'-'effective_at') THEN
    RETURN NEW;
   END IF;
  ELSIF TG_TABLE_NAME='appeals' THEN
   IF OLD.outcome IS NULL
    AND (to_jsonb(NEW)-'decided_by'-'outcome'-'decided_at')=(to_jsonb(OLD)-'decided_by'-'outcome'-'decided_at') THEN
    RETURN NEW;
   END IF;
  ELSIF TG_TABLE_NAME='case_assignments' THEN
   IF OLD.released_at IS NULL AND NEW.released_at IS NOT NULL
    AND (to_jsonb(NEW)-'released_at')=(to_jsonb(OLD)-'released_at') THEN
    RETURN NEW;
   END IF;
  ELSIF TG_TABLE_NAME='cases' THEN
   IF NEW.id=OLD.id AND NEW.subject=OLD.subject AND NEW.opened_at=OLD.opened_at
    AND NEW.version=OLD.version+1 AND OLD.state='open' THEN
    RETURN NEW;
   END IF;
  ELSIF TG_TABLE_NAME='reports' THEN
   IF OLD.state='open' AND NEW.state='closed' AND (to_jsonb(NEW)-'state')=(to_jsonb(OLD)-'state') THEN
    RETURN NEW;
   END IF;
  END IF;
 END IF;
 RAISE EXCEPTION 'case_history_immutable' USING ERRCODE='55000';
END $$;
CREATE TRIGGER case_immutable BEFORE UPDATE OR DELETE ON ts.cases FOR EACH ROW EXECUTE FUNCTION ts.preserve_case_history();
CREATE TRIGGER report_immutable BEFORE UPDATE OR DELETE ON ts.reports FOR EACH ROW EXECUTE FUNCTION ts.preserve_case_history();
CREATE TRIGGER assignment_immutable BEFORE UPDATE OR DELETE ON ts.case_assignments FOR EACH ROW EXECUTE FUNCTION ts.preserve_case_history();
CREATE TRIGGER case_event_immutable BEFORE UPDATE OR DELETE ON ts.case_events FOR EACH ROW EXECUTE FUNCTION ts.preserve_case_history();
CREATE TRIGGER action_immutable BEFORE UPDATE OR DELETE ON ts.actions FOR EACH ROW EXECUTE FUNCTION ts.preserve_case_history();
CREATE TRIGGER appeal_immutable BEFORE UPDATE OR DELETE ON ts.appeals FOR EACH ROW EXECUTE FUNCTION ts.preserve_case_history();

CREATE FUNCTION ts.assigned(p_case uuid,p_actor audit.reference) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT FROM ts.case_assignments WHERE case_id=p_case AND assignee=p_actor AND released_at IS NULL) $$;

-- A reporter, subject or earlier decider of the case has a conflict.
CREATE FUNCTION ts.conflicted(p_case uuid,p_actor audit.reference) RETURNS boolean
 LANGUAGE sql STABLE SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT FROM ts.cases WHERE id=p_case AND subject=p_actor)
  OR EXISTS(SELECT FROM ts.reports WHERE case_id=p_case AND reporter=p_actor) $$;

CREATE FUNCTION ts.effect(p_action ts.actions) RETURNS void
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 INSERT INTO ts.outbox(event_type,payload) VALUES('ts.action.effective.v1',jsonb_build_object(
  'action_id',p_action.id,'case_id',p_action.case_id,'subject',p_action.subject,'kind',p_action.kind,
  'reason_code',p_action.reason_code,'policy_version',p_action.policy_version,
  'duration_hours',p_action.duration_hours,'notice_key',p_action.notice_key,'revokes',p_action.revokes,
  'effective_at',to_char(p_action.effective_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')));
 INSERT INTO ts.case_events(case_id,kind,actor,resource)
 VALUES(p_action.case_id,CASE WHEN p_action.kind='revocation' THEN 'action_revoked' ELSE 'action_effective' END,
  COALESCE(p_action.approved_by,p_action.proposed_by),p_action.id);
END $$;

-- Intake from an authenticated reporter. The owner of the target supplies the
-- reported subject from its own snapshot; a duplicate open report is returned
-- unchanged rather than amplifying coordinated reporting.
CREATE FUNCTION ts.report_submit(p_event audit.reference,p_reporter audit.reference,p_policy audit.reference,
 p_target_type text,p_target uuid,p_subject audit.reference,p_category text,p_description uuid)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE prior ts.reports%ROWTYPE; selected uuid; created uuid; level text:=ts.severity(p_category);
BEGIN
 IF p_event IS NULL OR p_reporter IS NULL OR p_policy IS NULL OR p_target IS NULL OR p_subject IS NULL OR level IS NULL
  OR p_target_type NOT IN('account','listing_revision','photo','review','conversation','booking') THEN
  RAISE EXCEPTION 'invalid_report' USING ERRCODE='22023';
 END IF;
 IF p_reporter=p_subject THEN RAISE EXCEPTION 'report_self_target' USING ERRCODE='42501'; END IF;
 IF p_description IS NOT NULL AND NOT EXISTS(SELECT FROM ts.evidence_manifests WHERE id=p_description AND state='stored'
   AND provenance='report_description' AND purpose='report') THEN
  RAISE EXCEPTION 'invalid_report' USING ERRCODE='22023';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('report:'||p_reporter::text||':'||p_target_type||':'||p_target::text,0));
 SELECT * INTO prior FROM ts.reports WHERE reporter=p_reporter AND target_type=p_target_type AND target_id=p_target AND state='open';
 IF FOUND THEN
  RETURN jsonb_build_object('report_id',prior.id,'duplicate',true);
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('case-subject:'||p_subject::text,0));
 SELECT id INTO selected FROM ts.cases WHERE subject=p_subject AND severity=level AND state='open' ORDER BY opened_at LIMIT 1 FOR UPDATE;
 IF NOT FOUND THEN
  INSERT INTO ts.cases(subject,severity) VALUES(p_subject,level) RETURNING id INTO selected;
  INSERT INTO ts.case_events(case_id,kind,actor,resource) VALUES(selected,'opened',p_reporter,NULL);
 ELSE
  UPDATE ts.cases SET version=version+1 WHERE id=selected;
 END IF;
 INSERT INTO ts.reports(reporter,target_type,target_id,subject,category,description_evidence,case_id)
 VALUES(p_reporter,p_target_type,p_target,p_subject,p_category,p_description,selected) RETURNING id INTO created;
 INSERT INTO ts.case_events(case_id,kind,actor,resource) VALUES(selected,'report_linked',p_reporter,created);
 PERFORM audit.append(p_event,'report.received',created,'case_review',p_policy,selected);
 -- The reporter learns only that the report was received, never the case.
 RETURN jsonb_build_object('report_id',created,'duplicate',false);
END $$;

CREATE FUNCTION ts.case_assign(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_case uuid,p_assignee audit.reference)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE c ts.cases%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_case IS NULL OR p_assignee IS NULL THEN
  RAISE EXCEPTION 'invalid_case_command' USING ERRCODE='22023';
 END IF;
 SELECT * INTO c FROM ts.cases WHERE id=p_case FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'case_not_found' USING ERRCODE='P0002'; END IF;
 IF c.state<>'open' THEN RAISE EXCEPTION 'case_closed' USING ERRCODE='55000'; END IF;
 IF ts.conflicted(p_case,p_actor) OR ts.conflicted(p_case,p_assignee) THEN
  RAISE EXCEPTION 'case_conflict_of_interest' USING ERRCODE='42501';
 END IF;
 IF ts.assigned(p_case,p_assignee) THEN
  PERFORM audit.append(p_event,'case.assigned',p_case,'case_review',p_policy,p_case);
  RETURN jsonb_build_object('case_id',p_case,'assignee',p_assignee);
 END IF;
 UPDATE ts.case_assignments SET released_at=clock_timestamp() WHERE case_id=p_case AND released_at IS NULL;
 INSERT INTO ts.case_assignments(case_id,assignee,assigned_by) VALUES(p_case,p_assignee,p_actor);
 UPDATE ts.cases SET version=version+1 WHERE id=p_case;
 INSERT INTO ts.case_events(case_id,kind,actor,resource) VALUES(p_case,'assigned',p_actor,NULL);
 PERFORM audit.append(p_event,'case.assigned',p_case,'case_review',p_policy,p_case);
 RETURN jsonb_build_object('case_id',p_case,'assignee',p_assignee);
END $$;

-- Triage view for staff: severity-first, no subject, reporter or content.
-- Cases where the viewer is the subject or a reporter are omitted.
CREATE FUNCTION ts.case_queue(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,p_limit int)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50 THEN
  RAISE EXCEPTION 'invalid_case_command' USING ERRCODE='22023';
 END IF;
 RETURN COALESCE((SELECT jsonb_agg(item ORDER BY severity,opened_at) FROM (
  SELECT c.severity,c.opened_at,jsonb_build_object('id',c.id,'severity',c.severity,
   'opened_at',to_char(c.opened_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
   'reports',(SELECT count(*) FROM ts.reports r WHERE r.case_id=c.id AND r.state='open'),
   'assigned',EXISTS(SELECT FROM ts.case_assignments a WHERE a.case_id=c.id AND a.released_at IS NULL),
   'assigned_to_me',ts.assigned(c.id,p_actor),
   'pending_approval',EXISTS(SELECT FROM ts.actions x WHERE x.case_id=c.id AND x.state='proposed' AND x.proposed_by<>p_actor)) item
  FROM ts.cases c WHERE c.state='open' AND NOT ts.conflicted(c.id,p_actor)
  ORDER BY c.severity,c.opened_at LIMIT p_limit) q),'[]');
END $$;

-- Only the assigned, non-conflicted reviewer sees the case. Reporter
-- identities are not returned; evidence opens separately and is audited.
CREATE FUNCTION ts.case_detail(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,p_case uuid)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE body jsonb;
BEGIN
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_case IS NULL THEN
  RAISE EXCEPTION 'invalid_case_command' USING ERRCODE='22023';
 END IF;
 IF NOT ts.assigned(p_case,p_actor) OR ts.conflicted(p_case,p_actor) THEN
  RAISE EXCEPTION 'case_not_assigned' USING ERRCODE='42501';
 END IF;
 SELECT jsonb_build_object('id',c.id,'subject',c.subject,'severity',c.severity,'state',c.state,'version',c.version::text,
  'opened_at',to_char(c.opened_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'reports',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',r.id,'target_type',r.target_type,'target_id',r.target_id,
    'category',r.category,'description_evidence',r.description_evidence,'state',r.state) ORDER BY r.received_at)
    FROM ts.reports r WHERE r.case_id=c.id),'[]'),
  'evidence',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',e.id,'provenance',e.provenance,'media_type',e.media_type,'state',e.state) ORDER BY e.captured_at)
    FROM ts.evidence_manifests e WHERE e.case_id=c.id),'[]'),
  'actions',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',a.id,'kind',a.kind,'state',a.state,'reason_code',a.reason_code,
    'revokes',a.revokes,'proposed_by_self',a.proposed_by=p_actor) ORDER BY a.proposed_at)
    FROM ts.actions a WHERE a.case_id=c.id),'[]'))
 INTO body FROM ts.cases c WHERE c.id=p_case;
 PERFORM audit.append(p_event,'evidence.accessed',p_case,'case_review',p_policy,p_case);
 RETURN body;
END $$;

CREATE FUNCTION ts.action_propose(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_case uuid,p_kind text,p_reason text,p_action_policy text,p_duration_hours int,p_notice text)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE c ts.cases%ROWTYPE; created ts.actions%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_case IS NULL OR p_kind IS NULL OR p_kind='revocation' THEN
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

-- The second reviewer must be different from the proposer and the subject
-- and not conflicted; assignment is not required so a lead can approve.
CREATE FUNCTION ts.action_approve(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,p_action uuid)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE a ts.actions%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_action IS NULL THEN
  RAISE EXCEPTION 'invalid_case_command' USING ERRCODE='22023';
 END IF;
 SELECT * INTO a FROM ts.actions WHERE id=p_action FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'action_not_found' USING ERRCODE='P0002'; END IF;
 IF a.state='effective' THEN
  IF a.approved_by=p_actor THEN RETURN jsonb_build_object('action_id',a.id,'state',a.state); END IF;
  RAISE EXCEPTION 'action_already_effective' USING ERRCODE='55000';
 END IF;
 IF a.proposed_by=p_actor OR ts.conflicted(a.case_id,p_actor) THEN
  RAISE EXCEPTION 'action_second_reviewer_required' USING ERRCODE='42501';
 END IF;
 UPDATE ts.actions SET state='effective',approved_by=p_actor,effective_at=clock_timestamp() WHERE id=p_action RETURNING * INTO a;
 PERFORM ts.effect(a);
 PERFORM audit.append(p_event,'action.decided',a.id,'case_review',p_policy,a.case_id);
 RETURN jsonb_build_object('action_id',a.id,'state',a.state);
END $$;

CREATE FUNCTION ts.revoke(p_case uuid,p_target ts.actions,p_actor audit.reference,p_reason text) RETURNS ts.actions
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE created ts.actions%ROWTYPE;
BEGIN
 INSERT INTO ts.actions(case_id,subject,kind,reason_code,policy_version,notice_key,revokes,proposed_by,state,effective_at)
 VALUES(p_case,p_target.subject,'revocation',p_reason,p_target.policy_version,'actionRevoked',p_target.id,p_actor,'effective',clock_timestamp())
 RETURNING * INTO created;
 PERFORM ts.effect(created);
 RETURN created;
END $$;

-- Revoking never rewrites history: it records a linked revocation action.
CREATE FUNCTION ts.action_revoke(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,p_action uuid,p_reason text)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE a ts.actions%ROWTYPE; created ts.actions%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_action IS NULL THEN
  RAISE EXCEPTION 'invalid_case_command' USING ERRCODE='22023';
 END IF;
 SELECT * INTO created FROM ts.actions WHERE id=(SELECT resource_id FROM audit.log WHERE event_id=p_event AND action='action.decided' LIMIT 1);
 IF FOUND THEN
  IF created.revokes IS DISTINCT FROM p_action OR created.proposed_by<>p_actor THEN
   RAISE EXCEPTION 'case_command_conflict' USING ERRCODE='23505';
  END IF;
  RETURN jsonb_build_object('action_id',created.id,'revokes',created.revokes);
 END IF;
 SELECT * INTO a FROM ts.actions WHERE id=p_action FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'action_not_found' USING ERRCODE='P0002'; END IF;
 IF a.kind='revocation' OR a.state<>'effective' THEN RAISE EXCEPTION 'action_not_revocable' USING ERRCODE='55000'; END IF;
 IF NOT ts.assigned(a.case_id,p_actor) OR ts.conflicted(a.case_id,p_actor) THEN
  RAISE EXCEPTION 'case_not_assigned' USING ERRCODE='42501';
 END IF;
 IF EXISTS(SELECT FROM ts.actions WHERE revokes=a.id) THEN RAISE EXCEPTION 'action_already_revoked' USING ERRCODE='55000'; END IF;
 created:=ts.revoke(a.case_id,a,p_actor,p_reason);
 PERFORM audit.append(p_event,'action.decided',created.id,'case_review',p_policy,a.case_id);
 RETURN jsonb_build_object('action_id',created.id,'revokes',a.id);
END $$;

-- The affected person may always appeal an effective action once. No window
-- is enforced until an approved appeal policy exists (D07).
CREATE FUNCTION ts.appeal_submit(p_event audit.reference,p_appellant audit.reference,p_policy audit.reference,
 p_action uuid,p_statement uuid)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE a ts.actions%ROWTYPE; prior ts.appeals%ROWTYPE; created uuid;
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
 PERFORM pg_advisory_xact_lock(hashtextextended('appeal:'||p_action::text,0));
 SELECT * INTO prior FROM ts.appeals WHERE action_id=p_action;
 IF FOUND THEN RETURN jsonb_build_object('appeal_id',prior.id,'duplicate',true); END IF;
 INSERT INTO ts.appeals(action_id,appellant,statement_evidence) VALUES(p_action,p_appellant,p_statement) RETURNING id INTO created;
 INSERT INTO ts.case_events(case_id,kind,actor,resource) VALUES(a.case_id,'appeal_submitted',p_appellant,created);
 RETURN jsonb_build_object('appeal_id',created,'duplicate',false);
END $$;

-- An appeal is decided by someone who took no part in the action.
CREATE FUNCTION ts.appeal_decide(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_appeal uuid,p_outcome text)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE ap ts.appeals%ROWTYPE; a ts.actions%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_appeal IS NULL OR p_outcome NOT IN('upheld','overturned') THEN
  RAISE EXCEPTION 'invalid_appeal' USING ERRCODE='22023';
 END IF;
 SELECT * INTO ap FROM ts.appeals WHERE id=p_appeal FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'appeal_not_found' USING ERRCODE='P0002'; END IF;
 SELECT * INTO a FROM ts.actions WHERE id=ap.action_id FOR UPDATE;
 IF ap.outcome IS NOT NULL THEN
  IF ap.decided_by=p_actor AND ap.outcome=p_outcome THEN RETURN jsonb_build_object('appeal_id',ap.id,'outcome',ap.outcome); END IF;
  RAISE EXCEPTION 'appeal_already_decided' USING ERRCODE='55000';
 END IF;
 IF p_actor IN(a.proposed_by,a.subject) OR p_actor=a.approved_by OR ts.conflicted(a.case_id,p_actor) THEN
  RAISE EXCEPTION 'appeal_independent_reviewer_required' USING ERRCODE='42501';
 END IF;
 UPDATE ts.appeals SET decided_by=p_actor,outcome=p_outcome,decided_at=clock_timestamp() WHERE id=p_appeal;
 INSERT INTO ts.case_events(case_id,kind,actor,resource) VALUES(a.case_id,'appeal_decided',p_actor,p_appeal);
 IF p_outcome='overturned' AND NOT EXISTS(SELECT FROM ts.actions WHERE revokes=a.id) THEN
  PERFORM ts.revoke(a.case_id,a,p_actor,'appeal_overturned');
 END IF;
 PERFORM audit.append(p_event,'appeal.decided',p_appeal,'case_review',p_policy,a.case_id);
 RETURN jsonb_build_object('appeal_id',p_appeal,'outcome',p_outcome);
END $$;

-- P10 evidence access now requires the actor's active, non-conflicted case
-- assignment (AccessGuard). Legal requests remain gated by P12.
CREATE OR REPLACE FUNCTION ts.evidence_open(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_id uuid,p_justification text)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE m ts.evidence_manifests%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_id IS NULL
  OR p_justification IS NULL OR p_justification NOT IN('case_review','appeal_review','legal_request') THEN
  RAISE EXCEPTION 'invalid_evidence_access' USING ERRCODE='22023';
 END IF;
 SELECT * INTO m FROM ts.evidence_manifests WHERE id=p_id FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'evidence_not_found' USING ERRCODE='P0002'; END IF;
 IF NOT ts.assigned(m.case_id,p_actor) OR ts.conflicted(m.case_id,p_actor) THEN
  RAISE EXCEPTION 'case_not_assigned' USING ERRCODE='42501';
 END IF;
 INSERT INTO ts.evidence_access_events(event_id,human_actor,policy_version,evidence_id,justification,outcome)
 VALUES(p_event,p_actor,p_policy::uuid,m.id,p_justification,CASE WHEN m.state='stored' THEN 'granted' ELSE 'not_stored' END);
 PERFORM audit.append(p_event,'evidence.accessed',m.id,
  CASE WHEN p_justification='legal_request' THEN 'legal_request' ELSE 'case_review' END,p_policy,m.case_id);
 IF m.state<>'stored' THEN RETURN NULL; END IF;
 RETURN jsonb_build_object('id',m.id,'purpose',m.purpose,'case_id',m.case_id,'actor',m.actor,'provenance',m.provenance,
  'policy_version',m.policy_version,'media_type',m.media_type,'size',m.size,'sha256',encode(m.sha256,'hex'),
  'key_id',m.key_id,'wrapped_key',translate(encode(m.wrapped_key,'base64'),chr(10),''),'cipher_sha256',encode(m.cipher_sha256,'hex'),
  'cipher_size',m.cipher_size,
  'captured_at',to_char(m.captured_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'retain_until',to_char(m.retain_until AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"'),
  'location',jsonb_build_object('bucket',m.bucket,'key',m.object_key,'version_id',m.version_id));
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA ts FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA ts FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA ts FROM PUBLIC;
