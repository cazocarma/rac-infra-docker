-- P08 foundation. No runtime cutover or automatic approval. Old profiles get
-- only an unpublished envelope; their mutable text is not certified or erased.
SET LOCAL lock_timeout = '2s';
DO $$ BEGIN
 IF current_setting('server_encoding') <> 'UTF8' THEN
  RAISE EXCEPTION 'Listing canonical hashes require UTF8 database encoding';
 END IF;
END $$;

CREATE TABLE public.listings (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 compa_id uuid NOT NULL UNIQUE REFERENCES public.compa_perfil(id) ON DELETE CASCADE,
 state text NOT NULL DEFAULT 'unpublished' CHECK (state IN ('unpublished','published','suspended','removed')),
 published_revision_id uuid,
 pending_revision_id uuid,
 version bigint NOT NULL DEFAULT 0 CHECK (version >= 0),
 created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
 CHECK (state <> 'published' OR published_revision_id IS NOT NULL),
 CHECK (state <> 'unpublished' OR published_revision_id IS NULL),
 CHECK (pending_revision_id IS NULL OR pending_revision_id IS DISTINCT FROM published_revision_id)
);

CREATE TABLE public.listing_revisions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 listing_id uuid NOT NULL REFERENCES public.listings(id),
 revision_no bigint NOT NULL CHECK (revision_no > 0),
 payload_version text NOT NULL DEFAULT 'rac-listing-payload/1' CHECK (payload_version = 'rac-listing-payload/1'),
 -- One authoritative byte representation, with derived JSONB for querying.
 -- Digest matches SHA-256 of the exact UTF-8 Go canonical payload bytes.
 payload_canonical text NOT NULL CHECK (octet_length(payload_canonical) BETWEEN 2 AND 16384),
 payload jsonb GENERATED ALWAYS AS (payload_canonical::jsonb) STORED,
 payload_hash bytea GENERATED ALWAYS AS (public.digest(payload_canonical,'sha256')) STORED,
 assessment jsonb NOT NULL CHECK (jsonb_typeof(assessment) = 'object' AND octet_length(assessment::text) <= 65536),
 risk_score int NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
 policy_version text NOT NULL CHECK (policy_version ~ '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$'),
 submitted_at timestamptz NOT NULL DEFAULT statement_timestamp(),
 CHECK (jsonb_typeof(payload) = 'object'),
 UNIQUE (listing_id,revision_no),
 UNIQUE (id,listing_id)
);

ALTER TABLE public.listings
 ADD CONSTRAINT listing_published_revision_owner FOREIGN KEY (published_revision_id,id)
 REFERENCES public.listing_revisions(id,listing_id) DEFERRABLE INITIALLY DEFERRED,
 ADD CONSTRAINT listing_pending_revision_owner FOREIGN KEY (pending_revision_id,id)
 REFERENCES public.listing_revisions(id,listing_id) DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE public.listing_revision_decisions (
 revision_id uuid PRIMARY KEY REFERENCES public.listing_revisions(id),
 action text NOT NULL CHECK (action IN ('approved','rejected','changes_requested')),
 reviewer_subject text NOT NULL CHECK (reviewer_subject ~ '^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,254}$'),
 reason_code text NOT NULL CHECK (reason_code ~ '^[a-z][a-z0-9_]{1,63}$'),
 note_to_user_key text NOT NULL,
 reviewed_at timestamptz NOT NULL DEFAULT statement_timestamp(),
 CHECK ((action='approved' AND note_to_user_key='listingApproved')
     OR (action='rejected' AND note_to_user_key='listingRejected')
     OR (action='changes_requested' AND note_to_user_key='listingChangesRequested'))
);

CREATE INDEX listing_pending_queue ON public.listings(pending_revision_id) WHERE pending_revision_id IS NOT NULL;
CREATE INDEX listing_revision_risk_queue ON public.listing_revisions(risk_score DESC,submitted_at,id);

CREATE FUNCTION public.reject_listing_history_mutation() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 RAISE EXCEPTION 'Listing history is append-only' USING ERRCODE='55000';
END $$;
CREATE TRIGGER listing_revision_immutable BEFORE UPDATE OR DELETE ON public.listing_revisions
 FOR EACH ROW EXECUTE FUNCTION public.reject_listing_history_mutation();
CREATE TRIGGER listing_decision_immutable BEFORE UPDATE OR DELETE ON public.listing_revision_decisions
 FOR EACH ROW EXECUTE FUNCTION public.reject_listing_history_mutation();

CREATE FUNCTION public.advance_listing_version() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.version <> OLD.version + 1 THEN
  RAISE EXCEPTION 'Listing version must advance once' USING ERRCODE='40001';
 END IF;
 NEW.updated_at := statement_timestamp();
 RETURN NEW;
END $$;
CREATE TRIGGER listing_version BEFORE UPDATE ON public.listings
 FOR EACH ROW EXECUTE FUNCTION public.advance_listing_version();

CREATE FUNCTION public.check_listing_decision() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE pending uuid; owner_subject text;
BEGIN
 -- Same serialization point as submission/approval; a reviewer cannot decide
 -- an old revision after another instance has submitted a replacement.
 SELECT l.pending_revision_id,u.keycloak_id INTO pending,owner_subject
 FROM public.listing_revisions r JOIN public.listings l ON l.id=r.listing_id
 JOIN public.compa_perfil cp ON cp.id=l.compa_id JOIN public.usuario u ON u.id=cp.usuario_id
 WHERE r.id=NEW.revision_id FOR NO KEY UPDATE OF l;
 IF NOT FOUND OR pending IS DISTINCT FROM NEW.revision_id THEN
  RAISE EXCEPTION 'Listing revision is no longer pending' USING ERRCODE='40001';
 END IF;
 IF owner_subject=NEW.reviewer_subject THEN
  RAISE EXCEPTION 'Self review is forbidden' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER listing_decision_guard BEFORE INSERT ON public.listing_revision_decisions
 FOR EACH ROW EXECUTE FUNCTION public.check_listing_decision();

CREATE FUNCTION public.check_listing_pointers() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
DECLARE current_listing public.listings%ROWTYPE;
BEGIN
 -- Validate final transaction state, not an intermediate NEW tuple from an
 -- earlier update in the same transaction.
 SELECT * INTO current_listing FROM public.listings WHERE id=NEW.id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF current_listing.published_revision_id IS NOT NULL AND NOT EXISTS (
  SELECT FROM public.listing_revision_decisions d
  WHERE d.revision_id=current_listing.published_revision_id AND d.action='approved'
 ) THEN
  RAISE EXCEPTION 'Public revision has no human approval' USING ERRCODE='23514';
 END IF;
 IF current_listing.pending_revision_id IS NOT NULL AND EXISTS (
  SELECT FROM public.listing_revision_decisions d WHERE d.revision_id=current_listing.pending_revision_id
 ) THEN
  RAISE EXCEPTION 'Decided revision cannot remain pending' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER listing_pointer_guard AFTER INSERT OR UPDATE ON public.listings
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.check_listing_pointers();
-- A decision alone must not commit while leaving its revision pending.
CREATE FUNCTION public.check_listing_decision_pointer() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF EXISTS (SELECT FROM public.listings WHERE pending_revision_id=NEW.revision_id) THEN
  RAISE EXCEPTION 'Decision must atomically clear pending revision' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER listing_decision_pointer_guard AFTER INSERT ON public.listing_revision_decisions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.check_listing_decision_pointer();

REVOKE ALL ON FUNCTION public.reject_listing_history_mutation(),public.advance_listing_version(),
 public.check_listing_decision(),public.check_listing_pointers(),public.check_listing_decision_pointer() FROM PUBLIC;
GRANT SELECT ON public.listings,public.listing_revisions,public.listing_revision_decisions TO rac_user;
GRANT INSERT (compa_id) ON public.listings TO rac_user;
GRANT UPDATE (state,published_revision_id,pending_revision_id,version) ON public.listings TO rac_user;
GRANT INSERT (listing_id,revision_no,payload_canonical,assessment,risk_score,policy_version)
 ON public.listing_revisions TO rac_user;
GRANT INSERT (revision_id,action,reviewer_subject,reason_code,note_to_user_key)
 ON public.listing_revision_decisions TO rac_user;

INSERT INTO public.listings(compa_id) SELECT id FROM public.compa_perfil;
-- No grants to admin/match/chat/alert: T&S will call the owner's scoped API.
-- P12 needs an audited erasure/hold saga before purging revision history.
