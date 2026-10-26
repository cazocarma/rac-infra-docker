-- Authoritative, explicitly activated document sets. No activation is seeded.
CREATE SCHEMA documents;
REVOKE ALL ON SCHEMA documents FROM PUBLIC;
ALTER TABLE public.legal_documents ADD CONSTRAINT legal_document_identity UNIQUE(id,kind,locale);
ALTER TABLE public.legal_documents ADD CONSTRAINT legal_document_references CHECK(
 id<>'00000000-0000-0000-0000-000000000000'::uuid
 AND (approved_by IS NULL OR approved_by<>'00000000-0000-0000-0000-000000000000'::uuid));
ALTER TABLE public.legal_documents ADD CONSTRAINT legal_document_finite_times CHECK(
 isfinite(created_at) AND (reviewed_at IS NULL OR isfinite(reviewed_at))
 AND (published_at IS NULL OR isfinite(published_at)));

CREATE TABLE documents.head (
 locale text PRIMARY KEY CHECK(locale IN('es','en')),
 version bigint NOT NULL DEFAULT 0 CHECK(version>=0)
);
INSERT INTO documents.head(locale) VALUES('es'),('en');
CREATE TABLE documents.registry (
 event_id audit.reference PRIMARY KEY,
 locale text NOT NULL REFERENCES documents.head(locale),
 version bigint NOT NULL CHECK(version>0),
 policy_version audit.reference NOT NULL,
 approved_by audit.reference NOT NULL,
 effective_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 summary text[] NOT NULL,
 command jsonb NOT NULL,
 UNIQUE(locale,version)
);
CREATE TABLE documents.lineage (
 document_id uuid PRIMARY KEY,
 kind text NOT NULL,
 locale text NOT NULL,
 material_version uuid NOT NULL,
 FOREIGN KEY(document_id,kind,locale) REFERENCES public.legal_documents(id,kind,locale),
 FOREIGN KEY(material_version,kind,locale) REFERENCES public.legal_documents(id,kind,locale)
);
CREATE TABLE documents.requirement (
 locale text NOT NULL,
 version bigint NOT NULL,
 kind text NOT NULL,
 document_id uuid NOT NULL REFERENCES documents.lineage(document_id),
 PRIMARY KEY(locale,version,kind),
 FOREIGN KEY(locale,version) REFERENCES documents.registry(locale,version),
 FOREIGN KEY(document_id,kind,locale) REFERENCES public.legal_documents(id,kind,locale)
);

CREATE FUNCTION documents.immutable_record() RETURNS trigger LANGUAGE plpgsql
 SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'immutable_document_registry'; END $$;
CREATE TRIGGER immutable_document_registry BEFORE UPDATE OR DELETE ON documents.registry
 FOR EACH ROW EXECUTE FUNCTION documents.immutable_record();
CREATE TRIGGER immutable_document_lineage BEFORE UPDATE OR DELETE ON documents.lineage
 FOR EACH ROW EXECUTE FUNCTION documents.immutable_record();
CREATE TRIGGER immutable_document_requirement BEFORE UPDATE OR DELETE ON documents.requirement
 FOR EACH ROW EXECUTE FUNCTION documents.immutable_record();

-- Operator/staff ingress only: no application role receives EXECUTE here.
-- An authenticated human approval workflow must supply the review reference;
-- an arbitrary caller flag or business_admin role cannot publish a registry.
CREATE FUNCTION documents.activate(
 p_event uuid,p_expected bigint,p_locale text,p_documents uuid[],
 p_policy uuid,p_approval uuid,p_summary text[] DEFAULT ARRAY[]::text[]
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
 head_version bigint;
 prior documents.registry%ROWTYPE;
 command jsonb;
 ids uuid[];
 d public.legal_documents%ROWTYPE;
 previous public.legal_documents%ROWTYPE;
 historical public.legal_documents%ROWTYPE;
 material uuid;
 bound_material uuid;
 at_time timestamptz;
BEGIN
 IF p_event IS NULL OR p_event='00000000-0000-0000-0000-000000000000'::uuid
 OR p_expected IS NULL OR p_expected<0 OR p_locale IS NULL OR p_locale NOT IN('es','en')
 OR p_policy IS NULL OR p_policy='00000000-0000-0000-0000-000000000000'::uuid
 OR p_approval IS NULL OR p_approval='00000000-0000-0000-0000-000000000000'::uuid
 OR p_documents IS NULL OR coalesce(array_ndims(p_documents),0)<>1 OR cardinality(p_documents) NOT BETWEEN 4 AND 5 OR array_position(p_documents,NULL) IS NOT NULL
 OR p_summary IS NULL OR coalesce(array_ndims(p_summary),1)<>1 OR cardinality(p_summary)>3
 OR EXISTS(SELECT FROM unnest(p_summary) s WHERE s IS NULL OR length(btrim(s)) NOT BETWEEN 1 AND 280) THEN
  RAISE EXCEPTION 'invalid_document_activation' USING ERRCODE='22023';
 END IF;
 p_summary:=ARRAY(SELECT item FROM unnest(p_summary) item);
 SELECT array_agg(id ORDER BY id) INTO ids FROM unnest(p_documents) id;
 IF (SELECT count(DISTINCT id) FROM unnest(ids) id)<>cardinality(ids) THEN
  RAISE EXCEPTION 'duplicate_document' USING ERRCODE='22023';
 END IF;
 command:=jsonb_build_object('expected',p_expected,'locale',p_locale,'documents',to_jsonb(ids),
  'policy',p_policy,'approval',p_approval,'summary',to_jsonb(p_summary));
 -- Freeze the approved publication prefix while assigning immutable lineage.
 -- Publication ingress must take this same lock before writing document rows,
 -- then acquire the locale head; never reverse that order.
 LOCK TABLE public.legal_documents IN SHARE ROW EXCLUSIVE MODE;
 SELECT version INTO head_version FROM documents.head WHERE locale=p_locale FOR UPDATE;
 SELECT * INTO prior FROM documents.registry WHERE event_id=p_event;
 IF FOUND THEN
  IF prior.command<>command THEN RAISE EXCEPTION 'document_activation_conflict' USING ERRCODE='23505'; END IF;
  RETURN prior.version; -- A replay never rewinds the head or replaces a lineage.
 END IF;
 IF head_version<>p_expected THEN RAISE EXCEPTION 'document_registry_version_conflict' USING ERRCODE='40001'; END IF;
 at_time:=clock_timestamp();
 IF (SELECT count(*) FROM public.legal_documents WHERE id=ANY(ids) AND locale=p_locale
     AND legal_review='approved' AND published_at<=at_time)<>cardinality(ids)
 OR (SELECT count(DISTINCT kind) FROM public.legal_documents WHERE id=ANY(ids))<>cardinality(ids)
 OR EXISTS(SELECT required FROM unnest(ARRAY['terms_client','community_rules','privacy','safety_rules']) required
    WHERE NOT EXISTS(SELECT FROM public.legal_documents WHERE id=ANY(ids) AND kind=required)) THEN
  RAISE EXCEPTION 'unavailable_document_set' USING ERRCODE='22023';
 END IF;
 INSERT INTO documents.registry VALUES(p_event,p_locale,head_version+1,p_policy,p_approval,at_time,p_summary,command);
 FOR d IN SELECT * FROM public.legal_documents WHERE id=ANY(ids) ORDER BY kind LOOP
  SELECT doc.* INTO previous FROM documents.requirement r JOIN public.legal_documents doc ON doc.id=r.document_id
   WHERE r.locale=p_locale AND r.version=head_version AND r.kind=d.kind;
  IF FOUND AND d.id<>previous.id AND (d.published_at,d.created_at)<=(previous.published_at,previous.created_at) THEN
   RAISE EXCEPTION 'document_version_regression' USING ERRCODE='22023';
  END IF;
  -- Preserve existing bindings. For an unregistered historical version derive
  -- lineage from approved publication history, including material versions
  -- that were published between the previously active and selected documents.
  SELECT material_version INTO bound_material FROM documents.lineage WHERE document_id=d.id;
  IF FOUND THEN material:=bound_material;
  ELSE
   IF EXISTS(SELECT FROM public.legal_documents doc WHERE doc.kind=d.kind AND doc.locale=p_locale
     AND doc.legal_review='approved' AND doc.published_at<=d.published_at
     GROUP BY doc.published_at,doc.created_at HAVING count(*)>1) THEN
    RAISE EXCEPTION 'ambiguous_document_history' USING ERRCODE='22023';
   END IF;
   material:=NULL;
   FOR historical IN SELECT * FROM public.legal_documents doc
     WHERE doc.kind=d.kind AND doc.locale=p_locale AND doc.legal_review='approved'
      AND (doc.published_at,doc.created_at)<=(d.published_at,d.created_at)
     ORDER BY doc.published_at,doc.created_at LOOP
    SELECT material_version INTO bound_material FROM documents.lineage WHERE document_id=historical.id;
    IF FOUND THEN material:=bound_material;
    ELSE
     IF EXISTS(SELECT FROM documents.lineage l JOIN public.legal_documents frozen ON frozen.id=l.document_id
       WHERE l.kind=d.kind AND l.locale=p_locale
        AND (frozen.published_at,frozen.created_at)>(historical.published_at,historical.created_at)) THEN
      RAISE EXCEPTION 'backdated_document_history' USING ERRCODE='22023';
     END IF;
     IF material IS NULL OR historical.material_change THEN material:=historical.id; END IF;
     INSERT INTO documents.lineage VALUES(historical.id,historical.kind,p_locale,material);
    END IF;
   END LOOP;
  END IF;
  INSERT INTO documents.requirement VALUES(p_locale,head_version+1,d.kind,d.id);
 END LOOP;
 PERFORM audit.append(p_event,'policy.published',p_event,'operational',p_policy);
 UPDATE documents.head SET version=head_version+1 WHERE locale=p_locale;
 RETURN head_version+1;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA documents FROM PUBLIC;
REVOKE ALL ON FUNCTION documents.immutable_record(),documents.activate(uuid,bigint,text,uuid[],uuid,uuid,text[]) FROM PUBLIC;
GRANT USAGE ON SCHEMA documents TO rac_user,rac_backup;
GRANT SELECT ON documents.head,documents.lineage,documents.requirement TO rac_user;
GRANT SELECT(event_id,locale,version,policy_version,approved_by,effective_at,summary) ON documents.registry TO rac_user;
GRANT SELECT ON ALL TABLES IN SCHEMA documents TO rac_backup;
