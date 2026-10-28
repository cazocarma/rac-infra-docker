-- One editorial ledger for legal text and compa assessment definitions. Keep
-- existing document_id wire/ledger columns stable: the catalog makes the target
-- kind explicit with real FKs instead of inventing a legal-document placeholder.
CREATE TABLE documents.editorial_resource (
 resource_id uuid PRIMARY KEY,
 document_id uuid UNIQUE REFERENCES public.legal_documents(id),
 assessment_id uuid UNIQUE REFERENCES public.compa_attestation_versions(id),
 CHECK(num_nonnulls(document_id,assessment_id)=1 AND resource_id=coalesce(document_id,assessment_id))
);
INSERT INTO documents.editorial_resource(resource_id,document_id)
 SELECT document_id,document_id FROM documents.editorial_revision;
ALTER TABLE documents.editorial_revision DROP CONSTRAINT editorial_revision_document_id_fkey;
ALTER TABLE documents.editorial_revision ADD CONSTRAINT editorial_revision_resource_fkey
 FOREIGN KEY(document_id) REFERENCES documents.editorial_resource(resource_id);
CREATE TRIGGER immutable_editorial_resource BEFORE UPDATE OR DELETE ON documents.editorial_resource
 FOR EACH ROW EXECUTE FUNCTION documents.immutable_record();
REVOKE ALL ON documents.editorial_resource FROM PUBLIC;
GRANT SELECT ON documents.editorial_resource TO rac_backup;

CREATE OR REPLACE FUNCTION documents.draft_document(
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
 INSERT INTO documents.editorial_resource(resource_id,document_id) VALUES(p_document,p_document);
 INSERT INTO documents.editorial_revision(document_id,author_id) VALUES(p_document,p_actor);
 RETURN documents.editorial_record(p_event,p_document,p_actor,p_policy,'document.drafted',command);
END $$;

CREATE OR REPLACE FUNCTION documents.review_document(
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
 IF document.id IS NULL OR NOT EXISTS(SELECT FROM documents.editorial_resource WHERE resource_id=p_document AND document_id=p_document) OR author IS NULL OR document.published_at IS NOT NULL OR document.legal_review<>'pending'
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

CREATE OR REPLACE FUNCTION documents.publish_document(
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
 IF document.id IS NULL OR NOT EXISTS(SELECT FROM documents.editorial_resource WHERE resource_id=p_document AND document_id=p_document) OR review.document_id IS NULL OR review.decision<>'approved' OR document.published_at IS NOT NULL
 OR document.legal_review<>'approved' OR document.approved_by<>review.reviewer_id
 OR document.reviewed_at<>review.reviewed_at OR document.content_sha256<>review.content_sha256
 OR document.content_sha256<>decode(p_sha256,'hex') THEN
  RAISE EXCEPTION 'editorial_publication_not_approved' USING ERRCODE='40001';
 END IF;
 UPDATE public.legal_documents SET published_at=clock_timestamp() WHERE id=p_document;
 RETURN documents.editorial_record(p_event,p_document,p_actor,p_policy,'document.published',command);
END $$;

CREATE OR REPLACE FUNCTION documents.read_editorial_document(p_id uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object(
  'id',d.id,'kind',d.kind,'version',d.version,'locale',d.locale,
  'content',d.content,'sha256',encode(d.content_sha256,'hex'),
  'material_change',d.material_change,'author_id',e.author_id,
  'drafted_at',e.drafted_at,'decision',r.decision,'reviewer_id',r.reviewer_id,
  'reviewed_at',r.reviewed_at,'published_at',d.published_at)
 FROM public.legal_documents d JOIN documents.editorial_resource resource ON resource.document_id=d.id JOIN documents.editorial_revision e ON e.document_id=d.id
 LEFT JOIN documents.editorial_review r ON r.document_id=d.id
 WHERE d.id=p_id
$$;

CREATE FUNCTION documents.draft_assessment(
 p_event audit.reference,p_definition audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_version text,p_locale text,p_content text,p_sha256 audit.digest
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE command jsonb; prior uuid;
BEGIN
 IF p_event IS NULL OR p_definition IS NULL OR p_actor IS NULL OR p_policy IS NULL
 OR p_version IS NULL OR p_locale IS NULL OR p_content IS NULL OR p_sha256 IS NULL
 OR encode(public.digest(p_content,'sha256'),'hex')<>p_sha256 THEN
  RAISE EXCEPTION 'invalid_editorial_assessment' USING ERRCODE='22023';
 END IF;
 command:=jsonb_build_object('action','document.drafted','resource_kind','assessment','document',p_definition,
  'actor',p_actor,'policy',p_policy,'version',p_version,'locale',p_locale,'sha256',p_sha256);
 LOCK TABLE public.legal_documents IN SHARE ROW EXCLUSIVE MODE;
 LOCK TABLE public.compa_attestation_versions IN SHARE ROW EXCLUSIVE MODE;
 prior:=documents.editorial_replay(p_event,command);
 IF prior IS NOT NULL THEN RETURN prior; END IF;
 INSERT INTO public.compa_attestation_versions(id,version,locale,content) VALUES(p_definition,p_version,p_locale,p_content);
 INSERT INTO documents.editorial_resource(resource_id,assessment_id) VALUES(p_definition,p_definition);
 INSERT INTO documents.editorial_revision(document_id,author_id) VALUES(p_definition,p_actor);
 RETURN documents.editorial_record(p_event,p_definition,p_actor,p_policy,'document.drafted',command);
END $$;

CREATE FUNCTION documents.review_assessment(
 p_event audit.reference,p_definition audit.reference,p_actor audit.reference,p_policy audit.reference,
 p_sha256 audit.digest,p_decision text
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE command jsonb; prior uuid; author uuid; definition public.compa_attestation_versions%ROWTYPE; at_time timestamptz;
BEGIN
 IF p_event IS NULL OR p_definition IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_sha256 IS NULL
 OR p_decision IS NULL OR p_decision NOT IN('approved','rejected') THEN
  RAISE EXCEPTION 'invalid_editorial_review' USING ERRCODE='22023';
 END IF;
 command:=jsonb_build_object('action','document.reviewed','resource_kind','assessment','document',p_definition,
  'actor',p_actor,'policy',p_policy,'sha256',p_sha256,'decision',p_decision);
 LOCK TABLE public.legal_documents IN SHARE ROW EXCLUSIVE MODE;
 LOCK TABLE public.compa_attestation_versions IN SHARE ROW EXCLUSIVE MODE;
 prior:=documents.editorial_replay(p_event,command);
 IF prior IS NOT NULL THEN RETURN prior; END IF;
 SELECT * INTO definition FROM public.compa_attestation_versions WHERE id=p_definition;
 SELECT author_id INTO author FROM documents.editorial_revision WHERE document_id=p_definition;
 IF definition.id IS NULL OR author IS NULL OR NOT EXISTS(SELECT FROM documents.editorial_resource WHERE assessment_id=p_definition)
 OR definition.published_at IS NOT NULL OR definition.legal_review<>'pending'
 OR EXISTS(SELECT FROM documents.editorial_review WHERE document_id=p_definition)
 OR definition.content_sha256<>decode(p_sha256,'hex') THEN
  RAISE EXCEPTION 'editorial_revision_changed' USING ERRCODE='40001';
 END IF;
 IF author=p_actor THEN RAISE EXCEPTION 'editorial_self_review' USING ERRCODE='42501'; END IF;
 at_time:=clock_timestamp();
 PERFORM documents.editorial_record(p_event,p_definition,p_actor,p_policy,'document.reviewed',command);
 INSERT INTO documents.editorial_review(document_id,event_id,reviewer_id,decision,content_sha256,reviewed_at)
 VALUES(p_definition,p_event,p_actor,p_decision,decode(p_sha256,'hex'),at_time);
 IF p_decision='approved' THEN
  UPDATE public.compa_attestation_versions SET legal_review='approved',approved_by=p_actor,reviewed_at=at_time WHERE id=p_definition;
 END IF;
 RETURN p_definition;
END $$;

CREATE FUNCTION documents.publish_assessment(
 p_event audit.reference,p_definition audit.reference,p_actor audit.reference,p_policy audit.reference,p_sha256 audit.digest
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE command jsonb; prior uuid; definition public.compa_attestation_versions%ROWTYPE; review documents.editorial_review%ROWTYPE;
BEGIN
 IF p_event IS NULL OR p_definition IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_sha256 IS NULL THEN
  RAISE EXCEPTION 'invalid_editorial_publication' USING ERRCODE='22023';
 END IF;
 command:=jsonb_build_object('action','document.published','resource_kind','assessment','document',p_definition,
  'actor',p_actor,'policy',p_policy,'sha256',p_sha256);
 LOCK TABLE public.legal_documents IN SHARE ROW EXCLUSIVE MODE;
 LOCK TABLE public.compa_attestation_versions IN SHARE ROW EXCLUSIVE MODE;
 prior:=documents.editorial_replay(p_event,command);
 IF prior IS NOT NULL THEN RETURN prior; END IF;
 SELECT * INTO definition FROM public.compa_attestation_versions WHERE id=p_definition;
 SELECT * INTO review FROM documents.editorial_review WHERE document_id=p_definition;
 IF definition.id IS NULL OR NOT EXISTS(SELECT FROM documents.editorial_resource WHERE assessment_id=p_definition)
 OR review.document_id IS NULL OR review.decision<>'approved' OR definition.published_at IS NOT NULL
 OR definition.legal_review<>'approved' OR definition.approved_by<>review.reviewer_id
 OR definition.reviewed_at<>review.reviewed_at OR definition.content_sha256<>review.content_sha256
 OR definition.content_sha256<>decode(p_sha256,'hex') THEN
  RAISE EXCEPTION 'editorial_publication_not_approved' USING ERRCODE='40001';
 END IF;
 UPDATE public.compa_attestation_versions SET published_at=clock_timestamp() WHERE id=p_definition;
 RETURN documents.editorial_record(p_event,p_definition,p_actor,p_policy,'document.published',command);
END $$;

CREATE FUNCTION documents.read_editorial_assessment(p_id uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('id',d.id,'kind','compa_assessment','version',d.version,'locale',d.locale,
 'content',d.content,'sha256',encode(d.content_sha256,'hex'),'author_id',e.author_id,'drafted_at',e.drafted_at,
 'decision',r.decision,'reviewer_id',r.reviewer_id,'reviewed_at',r.reviewed_at,'published_at',d.published_at)
 FROM public.compa_attestation_versions d JOIN documents.editorial_resource resource ON resource.assessment_id=d.id
 JOIN documents.editorial_revision e ON e.document_id=d.id LEFT JOIN documents.editorial_review r ON r.document_id=d.id
 WHERE d.id=p_id
$$;

CREATE TABLE documents.editorial_activation (
 event_id audit.reference PRIMARY KEY,
 locale text NOT NULL,
 registry_version bigint NOT NULL,
 human_actor audit.reference NOT NULL,
 policy_version audit.reference NOT NULL,
 command jsonb NOT NULL,
 occurred_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(occurred_at)),
 FOREIGN KEY(locale,registry_version) REFERENCES documents.registry(locale,version)
);
CREATE TRIGGER immutable_editorial_activation BEFORE UPDATE OR DELETE ON documents.editorial_activation
 FOR EACH ROW EXECUTE FUNCTION documents.immutable_record();

CREATE FUNCTION documents.activate_editorial_bundle(
 p_event audit.reference,p_expected bigint,p_locale text,p_documents uuid[],p_hashes text[],
 p_definition audit.reference,p_assessment_sha audit.digest,p_actor audit.reference,p_policy audit.reference,p_summary text[]
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE command jsonb; selected jsonb; prior documents.editorial_activation%ROWTYPE; actual bigint; at_time timestamptz;
BEGIN
 IF p_event IS NULL OR p_expected IS NULL OR p_expected<0 OR p_locale IS NULL OR p_locale NOT IN('es','en')
 OR p_documents IS NULL OR cardinality(p_documents)<>5 OR array_ndims(p_documents)<>1 OR array_position(p_documents,NULL) IS NOT NULL
 OR p_hashes IS NULL OR cardinality(p_hashes)<>5 OR array_ndims(p_hashes)<>1 OR array_position(p_hashes,NULL) IS NOT NULL
 OR (SELECT count(DISTINCT id) FROM unnest(p_documents) id)<>5
 OR EXISTS(SELECT FROM unnest(p_hashes) h WHERE h !~ '^[0-9a-f]{64}$')
 OR p_definition IS NULL OR p_assessment_sha IS NULL OR p_actor IS NULL OR p_policy IS NULL OR p_summary IS NULL THEN
  RAISE EXCEPTION 'invalid_editorial_bundle' USING ERRCODE='22023';
 END IF;
 SELECT jsonb_agg(jsonb_build_object('id',id,'sha256',hash) ORDER BY id) INTO selected
 FROM unnest(p_documents,p_hashes) pair(id,hash);
 command:=jsonb_build_object('expected',p_expected,'locale',p_locale,'documents',selected,'assessment',p_definition,
  'assessment_sha256',p_assessment_sha,'actor',p_actor,'policy',p_policy,'summary',to_jsonb(p_summary));
 LOCK TABLE public.legal_documents IN SHARE ROW EXCLUSIVE MODE;
 LOCK TABLE public.compa_attestation_versions IN SHARE ROW EXCLUSIVE MODE;
 SELECT * INTO prior FROM documents.editorial_activation WHERE event_id=p_event;
 IF FOUND THEN
  IF prior.command<>command THEN RAISE EXCEPTION 'editorial_event_conflict' USING ERRCODE='23505'; END IF;
  RETURN prior.registry_version;
 END IF;
 -- Never retrofit a formerly independent operator activation into an atomic
 -- authenticated bundle, or reuse another editorial operation's nonce.
 IF EXISTS(SELECT FROM documents.registry WHERE event_id=p_event)
 OR EXISTS(SELECT FROM documents.editorial_event WHERE event_id=p_event) THEN
  RAISE EXCEPTION 'editorial_event_conflict' USING ERRCODE='23505';
 END IF;
 at_time:=clock_timestamp();
 IF (SELECT count(*) FROM unnest(p_documents,p_hashes) pair(id,hash)
 JOIN public.legal_documents d ON d.id=pair.id AND d.content_sha256=decode(pair.hash,'hex')
 JOIN documents.editorial_resource resource ON resource.document_id=d.id
 JOIN documents.editorial_review r ON r.document_id=d.id AND r.decision='approved'
 WHERE d.locale=p_locale AND d.legal_review='approved' AND d.published_at<=at_time
 AND d.approved_by=r.reviewer_id AND d.reviewed_at=r.reviewed_at AND d.content_sha256=r.content_sha256
 AND EXISTS(SELECT FROM documents.editorial_event e WHERE e.document_id=d.id AND e.action='document.published'))<>5
 OR NOT EXISTS(SELECT FROM public.compa_attestation_versions d
 JOIN documents.editorial_resource resource ON resource.assessment_id=d.id
 JOIN documents.editorial_review r ON r.document_id=d.id AND r.decision='approved'
 WHERE d.id=p_definition AND d.locale=p_locale AND d.legal_review='approved' AND d.published_at<=at_time
 AND d.content_sha256=decode(p_assessment_sha,'hex') AND d.content_sha256=r.content_sha256
 AND d.approved_by=r.reviewer_id AND d.reviewed_at=r.reviewed_at
 AND EXISTS(SELECT FROM documents.editorial_event e WHERE e.document_id=d.id AND e.action='document.published')) THEN
  RAISE EXCEPTION 'editorial_bundle_not_approved' USING ERRCODE='40001';
 END IF;
 actual:=documents.activate(p_event,p_expected,p_locale,p_documents,p_policy,p_actor,p_summary);
 INSERT INTO public.compa_attestation_requirements(locale,registry_version,definition_id) VALUES(p_locale,actual,p_definition);
 INSERT INTO documents.editorial_activation(event_id,locale,registry_version,human_actor,policy_version,command)
 VALUES(p_event,p_locale,actual,p_actor,p_policy,command);
 RETURN actual;
END $$;

REVOKE ALL ON documents.editorial_activation FROM PUBLIC;
GRANT SELECT ON documents.editorial_activation TO rac_backup;
REVOKE ALL ON FUNCTION
 documents.draft_assessment(audit.reference,audit.reference,audit.reference,audit.reference,text,text,text,audit.digest),
 documents.review_assessment(audit.reference,audit.reference,audit.reference,audit.reference,audit.digest,text),
 documents.publish_assessment(audit.reference,audit.reference,audit.reference,audit.reference,audit.digest),
 documents.read_editorial_assessment(uuid),
 documents.activate_editorial_bundle(audit.reference,bigint,text,uuid[],text[],audit.reference,audit.digest,audit.reference,audit.reference,text[]) FROM PUBLIC;
-- No login, grants to runtime, definition/text seed, or activation is created.
