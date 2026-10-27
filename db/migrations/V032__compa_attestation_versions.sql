-- No definitions or bindings are seeded. Runtime cannot publish or approve.
CREATE TABLE public.compa_attestation_versions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 version text NOT NULL CHECK(version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'),
 locale text NOT NULL CHECK(locale IN('es','en')),
 content text NOT NULL CHECK(octet_length(content) BETWEEN 1 AND 65536 AND jsonb_typeof(content::jsonb)='object'),
 content_sha256 bytea GENERATED ALWAYS AS (public.digest(content,'sha256')) STORED,
 legal_review text NOT NULL DEFAULT 'pending' CHECK(legal_review IN('pending','approved')),
 approved_by audit.reference,
 reviewed_at timestamptz,
 published_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(version,locale), UNIQUE(id,locale),
 CHECK(id<>'00000000-0000-0000-0000-000000000000'::uuid),
 CHECK(legal_review<>'approved' OR (approved_by IS NOT NULL AND reviewed_at IS NOT NULL)),
 CHECK(published_at IS NULL OR (legal_review='approved' AND published_at>=reviewed_at)),
 CHECK(isfinite(created_at) AND (reviewed_at IS NULL OR isfinite(reviewed_at)) AND (published_at IS NULL OR isfinite(published_at)))
);
CREATE FUNCTION public.preserve_compa_attestation_version() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'immutable_attestation_version'; END IF;
 IF (NEW.id,NEW.version,NEW.locale,NEW.content,NEW.created_at)
  IS DISTINCT FROM (OLD.id,OLD.version,OLD.locale,OLD.content,OLD.created_at)
 OR (OLD.published_at IS NOT NULL AND NEW IS DISTINCT FROM OLD)
 OR (OLD.legal_review='approved' AND NEW.legal_review<>'approved') THEN
  RAISE EXCEPTION 'immutable_attestation_version';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_attestation_version BEFORE UPDATE OR DELETE ON public.compa_attestation_versions
 FOR EACH ROW EXECUTE FUNCTION public.preserve_compa_attestation_version();

-- Reuse the same definition across nonmaterial registries without a new quiz.
CREATE TABLE public.compa_attestation_requirements (
 locale text NOT NULL,
 registry_version bigint NOT NULL,
 definition_id uuid NOT NULL,
 PRIMARY KEY(locale,registry_version),
 FOREIGN KEY(locale,registry_version) REFERENCES documents.registry(locale,version),
 FOREIGN KEY(definition_id,locale) REFERENCES public.compa_attestation_versions(id,locale)
);
CREATE TRIGGER immutable_attestation_requirement BEFORE UPDATE OR DELETE ON public.compa_attestation_requirements
 FOR EACH ROW EXECUTE FUNCTION documents.immutable_record();

CREATE TABLE public.compa_attestations (
 user_id uuid NOT NULL REFERENCES public.usuario(id) ON DELETE CASCADE,
 definition_id uuid NOT NULL REFERENCES public.compa_attestation_versions(id),
 locale text NOT NULL,
 registry_version bigint NOT NULL,
 policy_version audit.reference NOT NULL,
 statements jsonb NOT NULL CHECK(jsonb_typeof(statements)='object'),
 answers jsonb NOT NULL CHECK(jsonb_typeof(answers)='object'),
 quiz_passed_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK(isfinite(quiz_passed_at)),
 PRIMARY KEY(user_id,definition_id),
 FOREIGN KEY(locale,registry_version) REFERENCES documents.registry(locale,version),
 FOREIGN KEY(definition_id,locale) REFERENCES public.compa_attestation_versions(id,locale)
);
-- Runtime is append-only. Deletion remains reserved to the future reviewed
-- rights/retention workflow, rather than a trigger that would break erasure.
REVOKE ALL ON public.compa_attestation_versions,public.compa_attestation_requirements,public.compa_attestations FROM PUBLIC;
REVOKE ALL ON FUNCTION public.preserve_compa_attestation_version() FROM PUBLIC;
GRANT SELECT ON public.compa_attestation_versions,public.compa_attestation_requirements TO rac_user,rac_backup;
GRANT SELECT,INSERT ON public.compa_attestations TO rac_user;
GRANT SELECT ON public.compa_attestations TO rac_backup;
