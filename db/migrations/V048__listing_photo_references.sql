-- Bind a pending listing to exact processed bytes; this does not approve,
-- promote or publish a photo. V045's photo approval gate remains closed.
SET LOCAL lock_timeout='2s';

ALTER TABLE photo.processing_results ADD CONSTRAINT photo_result_reference
 UNIQUE(asset_id,attempt_id,normalized_sha256,normalized_size);

CREATE VIEW photo.ready_listing_sources AS
 SELECT s.id AS asset_id,s.owner_user_id,s.pipeline_version,r.attempt_id,
 r.normalized_sha256,r.normalized_size,r.risk_score
 FROM photo.sources s JOIN photo.upload_confirmations c ON c.asset_id=s.id
 JOIN photo.processing_results r ON r.asset_id=s.id
 JOIN photo.processing_jobs j ON j.asset_id=s.id
 WHERE j.completed AND r.disposition='needs_review';
REVOKE ALL ON photo.ready_listing_sources FROM PUBLIC;

CREATE TABLE photo.listing_references (
 revision_id uuid PRIMARY KEY,
 listing_id uuid NOT NULL,
 owner_user_id uuid NOT NULL,
 asset_id uuid NOT NULL,
 attempt_id uuid NOT NULL,
 normalized_sha256 bytea NOT NULL CHECK(octet_length(normalized_sha256)=32),
 normalized_size int NOT NULL CHECK(normalized_size BETWEEN 1 AND 5242880),
 FOREIGN KEY(revision_id,listing_id) REFERENCES public.listing_revisions(id,listing_id),
 FOREIGN KEY(asset_id,owner_user_id) REFERENCES photo.sources(id,owner_user_id),
 FOREIGN KEY(asset_id,attempt_id,normalized_sha256,normalized_size)
  REFERENCES photo.processing_results(asset_id,attempt_id,normalized_sha256,normalized_size)
);
CREATE INDEX photo_listing_reference_asset ON photo.listing_references(asset_id,revision_id);
CREATE TRIGGER photo_listing_reference_immutable BEFORE UPDATE OR DELETE ON photo.listing_references
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();
REVOKE ALL ON photo.listing_references FROM PUBLIC;

CREATE FUNCTION photo.owner_ready_reference(p_subject text,p_asset uuid,p_pipeline text)
 RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT FROM photo.ready_listing_sources s JOIN public.usuario u ON u.id=s.owner_user_id
 WHERE u.keycloak_id=p_subject AND s.asset_id=p_asset AND s.pipeline_version=p_pipeline);
$$;
REVOKE ALL ON FUNCTION photo.owner_ready_reference(text,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION photo.owner_ready_reference(text,uuid,text) TO rac_user;

CREATE FUNCTION photo.check_listing_source() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE selected text; ref photo.ready_listing_sources;
BEGIN
 selected:=NEW.payload_canonical::jsonb->>'photo_version';
 IF COALESCE(selected,'')='' THEN RETURN NEW; END IF;
 IF selected !~ '^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$' THEN
  RAISE EXCEPTION 'listing_photo_unavailable' USING ERRCODE='P0001';
 END IF;
 SELECT s.* INTO ref FROM photo.ready_listing_sources s
 JOIN public.listings l ON l.id=NEW.listing_id
 JOIN public.compa_perfil cp ON cp.id=l.compa_id AND cp.usuario_id=s.owner_user_id
 WHERE s.asset_id=selected::uuid;
 IF NOT FOUND THEN RAISE EXCEPTION 'listing_photo_unavailable' USING ERRCODE='P0001'; END IF;
 IF NEW.risk_score IS NULL OR NEW.risk_score NOT BETWEEN 0 AND 100 THEN
  RAISE EXCEPTION 'Invalid listing risk score' USING ERRCODE='23514';
 END IF;
 -- Photo signals affect triage, never an automatic account sanction. Keep
 -- only a technical reference here, not a duplicate OCR assessment/text.
 NEW.risk_score:=greatest(NEW.risk_score,ref.risk_score);
 NEW.assessment:=NEW.assessment||jsonb_build_object('photo',jsonb_build_object(
  'asset_id',ref.asset_id,'attempt_id',ref.attempt_id,
  'normalized_sha256',encode(ref.normalized_sha256,'hex'),
  'pipeline_version',ref.pipeline_version,'risk_score',ref.risk_score));
 RETURN NEW;
END $$;
CREATE TRIGGER listing_photo_prepare BEFORE INSERT ON public.listing_revisions
 FOR EACH ROW EXECUTE FUNCTION photo.check_listing_source();

CREATE FUNCTION photo.bind_listing_source() RETURNS trigger
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE selected text; inserted int;
BEGIN
 selected:=NEW.payload->>'photo_version';
 IF COALESCE(selected,'')='' THEN RETURN NEW; END IF;
 INSERT INTO photo.listing_references(revision_id,listing_id,owner_user_id,asset_id,attempt_id,normalized_sha256,normalized_size)
 SELECT NEW.id,NEW.listing_id,s.owner_user_id,s.asset_id,s.attempt_id,s.normalized_sha256,s.normalized_size
 FROM photo.ready_listing_sources s JOIN public.listings l ON l.id=NEW.listing_id
 JOIN public.compa_perfil cp ON cp.id=l.compa_id AND cp.usuario_id=s.owner_user_id
 WHERE s.asset_id=selected::uuid;
 GET DIAGNOSTICS inserted=ROW_COUNT;
 IF inserted<>1 THEN RAISE EXCEPTION 'listing_photo_unavailable' USING ERRCODE='P0001'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER listing_photo_bind AFTER INSERT ON public.listing_revisions
 FOR EACH ROW EXECUTE FUNCTION photo.bind_listing_source();
REVOKE ALL ON FUNCTION photo.check_listing_source(),photo.bind_listing_source() FROM PUBLIC;
-- No raw grants to the customer application or staff reader, and no new
-- approval permission. The immutable link is derived by the owner triggers.
