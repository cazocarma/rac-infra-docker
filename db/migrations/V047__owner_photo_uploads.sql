-- Owner recovery metadata; no public media, approval or runtime activation.
SET LOCAL lock_timeout='2s';
ALTER TABLE photo.sources ADD CONSTRAINT photo_source_owner UNIQUE(id,owner_user_id);
CREATE TABLE photo.upload_requests (
 owner_user_id uuid NOT NULL REFERENCES public.usuario(id),
 request_id uuid NOT NULL CHECK(request_id<>'00000000-0000-0000-0000-000000000000'),
 asset_id uuid NOT NULL UNIQUE,
 PRIMARY KEY(owner_user_id,request_id),
 FOREIGN KEY(asset_id,owner_user_id) REFERENCES photo.sources(id,owner_user_id)
);
CREATE TRIGGER photo_request_immutable BEFORE UPDATE OR DELETE ON photo.upload_requests
 FOR EACH ROW EXECUTE FUNCTION photo.preserve_history();
REVOKE ALL ON photo.upload_requests FROM PUBLIC;
GRANT SELECT ON photo.upload_requests TO rac_user;
GRANT INSERT(owner_user_id,request_id,asset_id) ON photo.upload_requests TO rac_user;

-- Do not grant raw job/results/assessment access to the public application.
-- Only this reduced owner view may cross that boundary. The trusted API binds
-- the subject from its validated principal, never from the public request body.
CREATE FUNCTION photo.owner_upload_status(p_subject text,p_asset uuid)
 RETURNS TABLE(asset_id text,state text)
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT s.id::text,CASE
  WHEN r.disposition='contact_correction_required' THEN 'correction_required'
  WHEN r.asset_id IS NOT NULL THEN 'awaiting_review'
  WHEN c.asset_id IS NULL THEN 'awaiting_upload'
  WHEN a.expires_at>clock_timestamp() THEN 'processing'
  WHEN j.attempts>=p.max_attempts AND j.available_at<=clock_timestamp() THEN 'processing_unavailable'
  ELSE 'queued' END
 FROM photo.sources s JOIN public.usuario u ON u.id=s.owner_user_id
 LEFT JOIN photo.upload_confirmations c ON c.asset_id=s.id
 LEFT JOIN photo.processing_jobs j ON j.asset_id=s.id
 LEFT JOIN photo.processing_attempts a ON a.id=j.active_attempt
 LEFT JOIN photo.processing_policies p ON p.pipeline_version=s.pipeline_version
 LEFT JOIN photo.processing_results r ON r.asset_id=s.id
 WHERE u.keycloak_id=p_subject AND s.id=p_asset;
$$;
REVOKE ALL ON FUNCTION photo.owner_upload_status(text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION photo.owner_upload_status(text,uuid) TO rac_user;
