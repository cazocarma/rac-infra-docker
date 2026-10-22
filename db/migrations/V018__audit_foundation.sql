-- RAC-AUDIT-1: privacy-minimal, serialized append. No application gets grants
-- automatically. Writer identities must be provisioned by the migration owner.
CREATE SCHEMA audit;
REVOKE ALL ON SCHEMA audit FROM PUBLIC;

DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='rac_audit_writer') THEN
  CREATE ROLE rac_audit_writer NOLOGIN;
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname='rac_audit_reader') THEN
  CREATE ROLE rac_audit_reader NOLOGIN;
 END IF;
END $$;

CREATE DOMAIN audit.reference AS uuid
 CHECK (VALUE <> '00000000-0000-0000-0000-000000000000'::uuid);
CREATE DOMAIN audit.digest AS text CHECK (VALUE ~ '^[0-9a-f]{64}$');

CREATE TABLE audit.chain_heads (
 chain_id audit.reference PRIMARY KEY,
 sequence bigint NOT NULL DEFAULT 0 CHECK (sequence >= 0),
 hash audit.digest NOT NULL DEFAULT repeat('0',64),
 CHECK (sequence > 0 OR hash=repeat('0',64))
);
-- session_user, not current_user: SECURITY DEFINER and SET ROLE must not let
-- a caller forge the authenticated database login. One login -> one chain.
CREATE TABLE audit.writer_principals (
 database_role name PRIMARY KEY,
 actor_id audit.reference NOT NULL,
 chain_id audit.reference NOT NULL REFERENCES audit.chain_heads(chain_id)
);

CREATE TABLE audit.log (
 chain_id audit.reference NOT NULL REFERENCES audit.chain_heads(chain_id),
 sequence bigint NOT NULL CHECK (sequence > 0),
 version integer NOT NULL CHECK (version=1),
 event_id audit.reference NOT NULL,
 occurred_at timestamptz NOT NULL,
 actor_id audit.reference NOT NULL,
 action text NOT NULL CHECK (action IN ('evidence.accessed','standing.changed','policy.published','listing.reviewed')),
 resource_id audit.reference NOT NULL,
 purpose text NOT NULL CHECK (purpose IN ('operational','case_review','legal_request','security')),
 policy_version audit.reference NOT NULL,
 case_id audit.reference,
 previous_hash audit.digest NOT NULL,
 hash audit.digest NOT NULL,
 PRIMARY KEY(chain_id,sequence),
 UNIQUE(chain_id,event_id)
);

CREATE FUNCTION audit.canonical_v1(
 p_chain uuid, p_sequence bigint, p_event uuid, p_at timestamptz,
 p_actor uuid, p_action text, p_resource uuid, p_purpose text,
 p_policy uuid, p_case uuid, p_previous text
) RETURNS text LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
 SET search_path=pg_catalog AS $$
 SELECT format('["rac.audit.v1","%s","%s","%s","%s","%s","%s","%s","%s","%s","%s","%s"]',
 p_chain,p_sequence,p_event,to_char(p_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
 p_actor,p_action,p_resource,p_purpose,p_policy,
 CASE WHEN p_case='00000000-0000-0000-0000-000000000000'::uuid THEN '' ELSE p_case::text END,p_previous)
$$;

-- No actor, chain, sequence, timestamp or digest is accepted from the caller.
-- The actor is the authenticated SERVICE principal, not a verified end-user.
-- Delegated staff actors require the separate authenticated ingress in P02.
CREATE FUNCTION audit.append(
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
 OR p_action IS NULL OR p_action NOT IN ('evidence.accessed','standing.changed','policy.published','listing.reviewed')
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

-- Default PUBLIC function execution must not create an alternate entry point.
REVOKE ALL ON ALL TABLES IN SCHEMA audit FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA audit FROM PUBLIC;
GRANT USAGE ON SCHEMA audit TO rac_audit_writer,rac_audit_reader;
GRANT EXECUTE ON FUNCTION audit.append(uuid,text,uuid,text,uuid,uuid) TO rac_audit_writer;
GRANT SELECT ON audit.log,audit.chain_heads TO rac_audit_reader;
COMMENT ON TABLE audit.log IS 'Pseudonymous metadata only. Hash chaining is tamper evidence against a trusted independent head, not WORM.';
