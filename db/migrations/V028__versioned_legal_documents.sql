SET search_path TO public;

-- No legal text is seeded or activated. Publication requires an explicit
-- reviewed record from the owner/operator; APIs cannot publish documents.
CREATE TABLE legal_documents (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 kind text NOT NULL CHECK(kind IN('terms_client','terms_compa','community_rules','privacy','safety_rules')),
 version text NOT NULL CHECK(version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
 locale text NOT NULL CHECK(locale IN('es','en')),
 content text NOT NULL CHECK(length(btrim(content))>0 AND octet_length(content)<=131072),
 content_sha256 bytea GENERATED ALWAYS AS (public.digest(content,'sha256')) STORED,
 material_change boolean NOT NULL,
 legal_review text NOT NULL DEFAULT 'pending' CHECK(legal_review IN('pending','approved')),
 approved_by uuid,
 reviewed_at timestamptz,
 published_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(kind,version,locale),
 CHECK(legal_review<>'approved' OR (approved_by IS NOT NULL AND reviewed_at IS NOT NULL)),
 CHECK(published_at IS NULL OR (legal_review='approved' AND published_at>=reviewed_at))
);
CREATE INDEX legal_documents_publication ON legal_documents(locale,kind,published_at DESC,id)
 WHERE published_at IS NOT NULL AND legal_review='approved';

CREATE FUNCTION preserve_legal_document() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable_legal_document'; END IF;
 IF (NEW.id,NEW.kind,NEW.version,NEW.locale,NEW.content,NEW.material_change,NEW.created_at)
    IS DISTINCT FROM (OLD.id,OLD.kind,OLD.version,OLD.locale,OLD.content,OLD.material_change,OLD.created_at)
 OR (OLD.published_at IS NOT NULL AND NEW IS DISTINCT FROM OLD)
 OR (OLD.legal_review='approved' AND NEW.legal_review<>'approved') THEN
  RAISE EXCEPTION 'immutable_legal_document';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_legal_document BEFORE UPDATE OR DELETE ON legal_documents
 FOR EACH ROW EXECUTE FUNCTION preserve_legal_document();

CREATE TABLE document_acceptances (
 user_id uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
 document_id uuid NOT NULL REFERENCES legal_documents(id),
 accepted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 context text NOT NULL CHECK(context IN('account','compa_onboarding','booking')),
 PRIMARY KEY(user_id,document_id)
);
REVOKE ALL ON legal_documents,document_acceptances FROM PUBLIC;
REVOKE ALL ON FUNCTION preserve_legal_document() FROM PUBLIC;
GRANT SELECT ON legal_documents TO rac_user;
GRANT SELECT,INSERT ON document_acceptances TO rac_user;
GRANT SELECT ON legal_documents,document_acceptances TO rac_backup;
