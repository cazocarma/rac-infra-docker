-- P10 EvidenceStore registry owned by the T&S domain (admin). It stores only
-- PII-free sealed manifests: digests, a wrapped data key, the exact object
-- version and retention. Plaintext and key-encryption keys never enter it.
-- No retention policy is seeded: capture is impossible until an operator
-- registers an approved policy version (D08/D14 remain pending decisions).
SET LOCAL lock_timeout='2s';

ALTER TABLE audit.log DROP CONSTRAINT log_action_check;
ALTER TABLE audit.log ADD CONSTRAINT log_action_check CHECK(action IN
 ('evidence.accessed','standing.changed','policy.published','listing.reviewed',
  'document.drafted','document.reviewed','document.published','evidence.captured'));

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
 OR p_action IS NULL OR p_action NOT IN ('evidence.accessed','standing.changed','policy.published','listing.reviewed','document.drafted','document.reviewed','document.published','evidence.captured')
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

CREATE SCHEMA ts;
REVOKE ALL ON SCHEMA ts FROM PUBLIC;

-- Operator-registered, immutable retention ceilings per purpose. Rows are
-- never seeded by migrations; registering one is an explicit, reviewed act.
CREATE TABLE ts.evidence_retention_policies (
 version text PRIMARY KEY CHECK(version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
 purpose text NOT NULL CHECK(purpose IN('report','case_review','appeal','legal_hold','authority_request')),
 max_days int NOT NULL CHECK(max_days BETWEEN 1 AND 3650),
 registered_by audit.reference NOT NULL,
 registered_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(registered_at)),
 retired_at timestamptz CHECK(retired_at IS NULL OR isfinite(retired_at))
);

CREATE TABLE ts.evidence_manifests (
 id uuid PRIMARY KEY,
 purpose text NOT NULL CHECK(purpose IN('report','case_review','appeal','legal_hold','authority_request')),
 case_id uuid NOT NULL,
 actor audit.reference NOT NULL,
 provenance text NOT NULL CHECK(provenance IN('report_description','listing_revision','photo','chat_excerpt','review','booking','imported_legacy')),
 policy_version text NOT NULL REFERENCES ts.evidence_retention_policies(version),
 media_type text NOT NULL CHECK(media_type IN('text/plain','application/json','image/jpeg','image/png')),
 size int NOT NULL CHECK(size BETWEEN 1 AND 10485760),
 sha256 bytea NOT NULL CHECK(octet_length(sha256)=32),
 key_id text NOT NULL CHECK(key_id ~ '^[A-Za-z0-9._:-]{1,128}$'),
 wrapped_key bytea NOT NULL CHECK(octet_length(wrapped_key) BETWEEN 1 AND 4096),
 cipher_sha256 bytea NOT NULL CHECK(octet_length(cipher_sha256)=32),
 cipher_size int NOT NULL CHECK(cipher_size BETWEEN 29 AND 10485788),
 captured_at timestamptz NOT NULL CHECK(isfinite(captured_at)),
 retain_until timestamptz NOT NULL CHECK(isfinite(retain_until) AND retain_until>captured_at),
 prepared_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 state text NOT NULL DEFAULT 'prepared' CHECK(state IN('prepared','stored')),
 bucket text CHECK(bucket ~ '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$'),
 object_key text CHECK(object_key=('evidence/'||left(id::text,2)||'/'||id::text||'.bin')),
 version_id text CHECK(length(version_id) BETWEEN 1 AND 1000 AND version_id ~ '^[A-Za-z0-9._:+/=-]+$'),
 stored_at timestamptz,
 CHECK((state='prepared' AND bucket IS NULL AND object_key IS NULL AND version_id IS NULL AND stored_at IS NULL)
  OR (state='stored' AND bucket IS NOT NULL AND object_key IS NOT NULL AND version_id IS NOT NULL AND stored_at IS NOT NULL))
);
CREATE INDEX evidence_by_case ON ts.evidence_manifests(case_id,captured_at);

CREATE TABLE ts.evidence_access_events (
 event_id uuid PRIMARY KEY,
 human_actor audit.reference NOT NULL,
 policy_version uuid NOT NULL,
 evidence_id uuid NOT NULL REFERENCES ts.evidence_manifests(id),
 justification text NOT NULL CHECK(justification IN('case_review','appeal_review','legal_request')),
 outcome text NOT NULL CHECK(outcome IN('granted','not_stored')),
 occurred_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Prepared intents only gain their storage location once; everything else is
-- append-only history, even for the migration owner's application paths.
CREATE FUNCTION ts.preserve_evidence() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 -- Nested by table: PL/pgSQL does not short-circuit record field lookups.
 IF TG_OP='UPDATE' THEN
  IF TG_TABLE_NAME='evidence_manifests' THEN
   IF OLD.state='prepared' AND NEW.state='stored'
    AND (to_jsonb(NEW)-'state'-'bucket'-'object_key'-'version_id'-'stored_at')
      =(to_jsonb(OLD)-'state'-'bucket'-'object_key'-'version_id'-'stored_at') THEN
    RETURN NEW;
   END IF;
  ELSIF TG_TABLE_NAME='evidence_retention_policies' THEN
   IF OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL
    AND (to_jsonb(NEW)-'retired_at')=(to_jsonb(OLD)-'retired_at') THEN
    RETURN NEW;
   END IF;
  END IF;
 END IF;
 RAISE EXCEPTION 'evidence_history_immutable' USING ERRCODE='55000';
END $$;
CREATE TRIGGER evidence_manifest_immutable BEFORE UPDATE OR DELETE ON ts.evidence_manifests
 FOR EACH ROW EXECUTE FUNCTION ts.preserve_evidence();
CREATE TRIGGER evidence_policy_immutable BEFORE UPDATE OR DELETE ON ts.evidence_retention_policies
 FOR EACH ROW EXECUTE FUNCTION ts.preserve_evidence();
CREATE TRIGGER evidence_access_immutable BEFORE UPDATE OR DELETE ON ts.evidence_access_events
 FOR EACH ROW EXECUTE FUNCTION ts.preserve_evidence();

CREATE FUNCTION ts.evidence_ready() RETURNS boolean
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ SELECT true $$;

-- Records the sealed manifest before any storage I/O. Replays with identical
-- content are accepted; any divergence is a conflict.
CREATE FUNCTION ts.evidence_prepare(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,p_manifest jsonb)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE m ts.evidence_manifests%ROWTYPE; prior ts.evidence_manifests%ROWTYPE; rule ts.evidence_retention_policies%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR jsonb_typeof(p_manifest)<>'object'
  OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_manifest) k)<>ARRAY['actor','captured_at','case_id','cipher_sha256','cipher_size','id','key_id','media_type','policy_version','provenance','purpose','retain_until','sha256','size','wrapped_key'] THEN
  RAISE EXCEPTION 'invalid_evidence_manifest' USING ERRCODE='22023';
 END IF;
 IF p_manifest->>'actor' IS DISTINCT FROM p_actor::text THEN
  RAISE EXCEPTION 'evidence_actor_mismatch' USING ERRCODE='42501';
 END IF;
 BEGIN
  m.id:=(p_manifest->>'id')::uuid; m.purpose:=p_manifest->>'purpose'; m.case_id:=(p_manifest->>'case_id')::uuid;
  m.actor:=p_actor; m.provenance:=p_manifest->>'provenance'; m.policy_version:=p_manifest->>'policy_version';
  m.media_type:=p_manifest->>'media_type'; m.size:=(p_manifest->>'size')::int;
  m.sha256:=decode(p_manifest->>'sha256','hex'); m.key_id:=p_manifest->>'key_id';
  m.wrapped_key:=decode(p_manifest->>'wrapped_key','base64'); m.cipher_sha256:=decode(p_manifest->>'cipher_sha256','hex');
  m.cipher_size:=(p_manifest->>'cipher_size')::int;
  m.captured_at:=(p_manifest->>'captured_at')::timestamptz; m.retain_until:=(p_manifest->>'retain_until')::timestamptz;
 EXCEPTION WHEN others THEN
  RAISE EXCEPTION 'invalid_evidence_manifest' USING ERRCODE='22023';
 END;
 SELECT * INTO rule FROM ts.evidence_retention_policies WHERE version=m.policy_version FOR SHARE;
 IF NOT FOUND OR rule.retired_at IS NOT NULL OR rule.purpose<>m.purpose THEN
  RAISE EXCEPTION 'evidence_policy_unavailable' USING ERRCODE='55000';
 END IF;
 IF m.captured_at>clock_timestamp()+interval '1 minute' OR m.captured_at<clock_timestamp()-interval '1 hour'
  OR m.retain_until<=clock_timestamp() OR m.retain_until>m.captured_at+make_interval(days=>rule.max_days) THEN
  RAISE EXCEPTION 'evidence_retention_outside_policy' USING ERRCODE='55000';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('evidence:'||m.id::text,0));
 SELECT * INTO prior FROM ts.evidence_manifests WHERE id=m.id;
 IF FOUND THEN
  IF (to_jsonb(prior)-'prepared_at'-'state'-'bucket'-'object_key'-'version_id'-'stored_at')
   <>(to_jsonb(m)-'prepared_at'-'state'-'bucket'-'object_key'-'version_id'-'stored_at') THEN
   RAISE EXCEPTION 'evidence_conflict' USING ERRCODE='23505';
  END IF;
  RETURN jsonb_build_object('id',prior.id,'state',prior.state);
 END IF;
 INSERT INTO ts.evidence_manifests(id,purpose,case_id,actor,provenance,policy_version,media_type,size,sha256,key_id,
  wrapped_key,cipher_sha256,cipher_size,captured_at,retain_until)
 VALUES(m.id,m.purpose,m.case_id,m.actor,m.provenance,m.policy_version,m.media_type,m.size,m.sha256,m.key_id,
  m.wrapped_key,m.cipher_sha256,m.cipher_size,m.captured_at,m.retain_until);
 RETURN jsonb_build_object('id',m.id,'state','prepared');
END $$;

-- Binds the exact stored version after the adapter verified COMPLIANCE
-- retention and byte readback. Only the preparing actor can complete it.
CREATE FUNCTION ts.evidence_commit(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_id uuid,p_bucket text,p_key text,p_version text)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE m ts.evidence_manifests%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_id IS NULL THEN
  RAISE EXCEPTION 'invalid_evidence_manifest' USING ERRCODE='22023';
 END IF;
 SELECT * INTO m FROM ts.evidence_manifests WHERE id=p_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'evidence_not_found' USING ERRCODE='P0002'; END IF;
 IF m.actor<>p_actor THEN RAISE EXCEPTION 'evidence_actor_mismatch' USING ERRCODE='42501'; END IF;
 IF m.state='stored' THEN
  IF m.bucket=p_bucket AND m.object_key=p_key AND m.version_id=p_version THEN
   PERFORM audit.append(p_event,'evidence.captured',m.id,'case_review',p_policy,m.case_id);
   RETURN jsonb_build_object('id',m.id,'state','stored');
  END IF;
  RAISE EXCEPTION 'evidence_conflict' USING ERRCODE='23505';
 END IF;
 UPDATE ts.evidence_manifests SET state='stored',bucket=p_bucket,object_key=p_key,version_id=p_version,stored_at=clock_timestamp()
 WHERE id=p_id;
 PERFORM audit.append(p_event,'evidence.captured',m.id,'case_review',p_policy,m.case_id);
 RETURN jsonb_build_object('id',m.id,'state','stored');
END $$;

-- Returns what is needed to open one stored object, after recording the
-- access and its audit event in the same transaction. Case assignment and
-- conflict-of-interest checks are added by the P11 AccessGuard.
CREATE FUNCTION ts.evidence_open(p_event audit.reference,p_actor audit.reference,p_policy audit.reference,
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
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA ts FROM PUBLIC;
-- No grants: an explicit DEV-only provisioning step creates the capture and
-- reader logins with EXECUTE on exact signatures only.
