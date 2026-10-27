-- Editorial commands are not granted to application roles. A future owner
-- ingress must authenticate delegated staff before supplying the human actor.
-- No document, approval, publisher account, policy or activation is seeded.
ALTER TABLE audit.log DROP CONSTRAINT log_action_check;
ALTER TABLE audit.log ADD CONSTRAINT log_action_check CHECK(action IN
 ('evidence.accessed','standing.changed','policy.published','listing.reviewed',
  'document.drafted','document.reviewed','document.published'));

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
 OR p_action IS NULL OR p_action NOT IN ('evidence.accessed','standing.changed','policy.published','listing.reviewed','document.drafted','document.reviewed','document.published')
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

CREATE TABLE documents.editorial_revision (
 document_id uuid PRIMARY KEY REFERENCES public.legal_documents(id),
 author_id audit.reference NOT NULL,
 drafted_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(drafted_at))
);
CREATE TABLE documents.editorial_event (
 event_id audit.reference PRIMARY KEY,
 document_id uuid NOT NULL REFERENCES documents.editorial_revision(document_id),
 action text NOT NULL CHECK(action IN('document.drafted','document.reviewed','document.published')),
 human_actor audit.reference NOT NULL,
 policy_version audit.reference NOT NULL,
 command jsonb NOT NULL CHECK(jsonb_typeof(command)='object'),
 occurred_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(occurred_at))
);
CREATE TABLE documents.editorial_review (
 document_id uuid PRIMARY KEY REFERENCES documents.editorial_revision(document_id),
 event_id audit.reference NOT NULL UNIQUE REFERENCES documents.editorial_event(event_id),
 reviewer_id audit.reference NOT NULL,
 decision text NOT NULL CHECK(decision IN('approved','rejected')),
 content_sha256 bytea NOT NULL CHECK(octet_length(content_sha256)=32),
 reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(reviewed_at))
);
CREATE TRIGGER immutable_editorial_revision BEFORE UPDATE OR DELETE ON documents.editorial_revision
 FOR EACH ROW EXECUTE FUNCTION documents.immutable_record();
CREATE TRIGGER immutable_editorial_event BEFORE UPDATE OR DELETE ON documents.editorial_event
 FOR EACH ROW EXECUTE FUNCTION documents.immutable_record();
CREATE TRIGGER immutable_editorial_review BEFORE UPDATE OR DELETE ON documents.editorial_review
 FOR EACH ROW EXECUTE FUNCTION documents.immutable_record();

-- Every entry point locks the publication prefix before any head locks, in the
-- same order as activate(). An audited replay cannot change content or actor.
CREATE FUNCTION documents.editorial_replay(p_event uuid,p_command jsonb)
 RETURNS uuid LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE prior documents.editorial_event%ROWTYPE;
BEGIN
 SELECT * INTO prior FROM documents.editorial_event WHERE event_id=p_event;
 IF FOUND THEN
  IF prior.command<>p_command THEN
   RAISE EXCEPTION 'editorial_event_conflict' USING ERRCODE='23505';
  END IF;
  RETURN prior.document_id;
 END IF;
 RETURN NULL;
END $$;
CREATE FUNCTION documents.editorial_record(p_event uuid,p_document uuid,p_actor uuid,p_policy uuid,p_action text,p_command jsonb)
 RETURNS uuid LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 INSERT INTO documents.editorial_event(event_id,document_id,human_actor,policy_version,action,command)
 VALUES(p_event,p_document,p_actor,p_policy,p_action,p_command);
 -- audit.actor_id remains the provisioned SERVICE principal. The verified
 -- delegated human is recorded above, correlated through the exact event id.
 -- No text, token, email, IP or free-form justification enters the audit chain.
 PERFORM audit.append(p_event,p_action,p_document,'operational',p_policy);
 RETURN p_document;
END $$;

CREATE FUNCTION documents.draft_document(
 p_event audit.reference,p_document audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_kind text,p_version text,p_locale text,p_content text,p_material boolean,p_sha256 audit.digest
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE command jsonb; prior uuid;
BEGIN
 IF p_event IS NULL OR p_document IS NULL OR p_actor IS NULL OR p_policy IS NULL
 OR p_kind IS NULL OR p_version IS NULL OR p_locale IS NULL OR p_content IS NULL OR p_material IS NULL OR p_sha256 IS NULL
 OR encode(public.digest(p_content,'sha256'),'hex')<>p_sha256 THEN
  RAISE EXCEPTION 'invalid_editorial_draft' USING ERRCODE='22023';
 END IF;
 command:=jsonb_build_object('action','document.drafted','document',p_document,'actor',p_actor,'policy',p_policy,
  'kind',p_kind,'version',p_version,'locale',p_locale,'sha256',p_sha256,'material_change',p_material);
 LOCK TABLE public.legal_documents IN SHARE ROW EXCLUSIVE MODE;
 prior:=documents.editorial_replay(p_event,command);
 IF prior IS NOT NULL THEN RETURN prior; END IF;
 INSERT INTO public.legal_documents(id,kind,version,locale,content,material_change)
 VALUES(p_document,p_kind,p_version,p_locale,p_content,p_material);
 INSERT INTO documents.editorial_revision(document_id,author_id) VALUES(p_document,p_actor);
 RETURN documents.editorial_record(p_event,p_document,p_actor,p_policy,'document.drafted',command);
END $$;

CREATE FUNCTION documents.review_document(
 p_event audit.reference,p_document audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_sha256 audit.digest,p_decision text
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE command jsonb; prior uuid; author uuid; document public.legal_documents%ROWTYPE; at_time timestamptz;
BEGIN
 IF p_event IS NULL OR p_document IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_sha256 IS NULL
 OR p_decision IS NULL OR p_decision NOT IN('approved','rejected') THEN
  RAISE EXCEPTION 'invalid_editorial_review' USING ERRCODE='22023';
 END IF;
 command:=jsonb_build_object('action','document.reviewed','document',p_document,'actor',p_actor,'policy',p_policy,
  'sha256',p_sha256,'decision',p_decision);
 LOCK TABLE public.legal_documents IN SHARE ROW EXCLUSIVE MODE;
 prior:=documents.editorial_replay(p_event,command);
 IF prior IS NOT NULL THEN RETURN prior; END IF;
 SELECT * INTO document FROM public.legal_documents WHERE id=p_document;
 SELECT author_id INTO author FROM documents.editorial_revision WHERE document_id=p_document;
 IF author IS NULL OR document.published_at IS NOT NULL OR document.legal_review<>'pending'
 OR EXISTS(SELECT FROM documents.editorial_review WHERE document_id=p_document)
 OR document.content_sha256<>decode(p_sha256,'hex') THEN
  RAISE EXCEPTION 'editorial_revision_changed' USING ERRCODE='40001';
 END IF;
 IF author=p_actor THEN RAISE EXCEPTION 'editorial_self_review' USING ERRCODE='42501'; END IF;
 at_time:=clock_timestamp();
 PERFORM documents.editorial_record(p_event,p_document,p_actor,p_policy,'document.reviewed',command);
 INSERT INTO documents.editorial_review(document_id,event_id,reviewer_id,decision,content_sha256,reviewed_at)
 VALUES(p_document,p_event,p_actor,p_decision,decode(p_sha256,'hex'),at_time);
 IF p_decision='approved' THEN
  UPDATE public.legal_documents SET legal_review='approved',approved_by=p_actor,reviewed_at=at_time WHERE id=p_document;
 END IF;
 RETURN p_document;
END $$;

CREATE FUNCTION documents.publish_document(
 p_event audit.reference,p_document audit.reference,p_actor audit.reference,p_policy audit.reference,p_sha256 audit.digest
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE command jsonb; prior uuid; document public.legal_documents%ROWTYPE; review documents.editorial_review%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_document IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_sha256 IS NULL THEN
  RAISE EXCEPTION 'invalid_editorial_publication' USING ERRCODE='22023';
 END IF;
 command:=jsonb_build_object('action','document.published','document',p_document,'actor',p_actor,'policy',p_policy,'sha256',p_sha256);
 LOCK TABLE public.legal_documents IN SHARE ROW EXCLUSIVE MODE;
 prior:=documents.editorial_replay(p_event,command);
 IF prior IS NOT NULL THEN RETURN prior; END IF;
 SELECT * INTO document FROM public.legal_documents WHERE id=p_document;
 SELECT * INTO review FROM documents.editorial_review WHERE document_id=p_document;
 IF review.document_id IS NULL OR review.decision<>'approved' OR document.published_at IS NOT NULL
 OR document.legal_review<>'approved' OR document.approved_by<>review.reviewer_id
 OR document.reviewed_at<>review.reviewed_at OR document.content_sha256<>review.content_sha256
 OR document.content_sha256<>decode(p_sha256,'hex') THEN
  RAISE EXCEPTION 'editorial_publication_not_approved' USING ERRCODE='40001';
 END IF;
 UPDATE public.legal_documents SET published_at=clock_timestamp() WHERE id=p_document;
 RETURN documents.editorial_record(p_event,p_document,p_actor,p_policy,'document.published',command);
END $$;

REVOKE ALL ON documents.editorial_revision,documents.editorial_event,documents.editorial_review FROM PUBLIC;
REVOKE ALL ON FUNCTION documents.editorial_replay(uuid,jsonb),documents.editorial_record(uuid,uuid,uuid,uuid,text,jsonb),
 documents.draft_document(audit.reference,audit.reference,audit.reference,audit.reference,text,text,text,text,boolean,audit.digest),
 documents.review_document(audit.reference,audit.reference,audit.reference,audit.reference,audit.digest,text),
 documents.publish_document(audit.reference,audit.reference,audit.reference,audit.reference,audit.digest) FROM PUBLIC;
GRANT SELECT ON documents.editorial_revision,documents.editorial_event,documents.editorial_review TO rac_backup;
-- No EXECUTE grants, no runtime INSERT/UPDATE/DELETE grants, no new login.
-- The authenticated ingress and its least-privilege binding remain gated.
