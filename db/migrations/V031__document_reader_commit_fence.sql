-- The current validated topology uses one PostgreSQL database and separate
-- service roles. Expose only the shared registry coordination primitive; match
-- and chat still cannot SELECT document or acceptance tables.
CREATE FUNCTION documents.lock_registry(p_locale text)
RETURNS TABLE(registry_version bigint,policy_version uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE locked_version bigint;
BEGIN
 SELECT h.version INTO locked_version FROM documents.head h WHERE h.locale=p_locale FOR SHARE;
 IF NOT FOUND OR locked_version=0 THEN
  RAISE EXCEPTION 'document_registry_unavailable' USING ERRCODE='55000';
 END IF;
 RETURN QUERY SELECT r.version,r.policy_version::uuid FROM documents.registry r
  WHERE r.locale=p_locale AND r.version=locked_version;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'document_registry_unavailable' USING ERRCODE='55000';
 END IF;
END $$;
REVOKE ALL ON FUNCTION documents.lock_registry(text) FROM PUBLIC;
GRANT USAGE ON SCHEMA documents TO rac_match,rac_chat;
GRANT EXECUTE ON FUNCTION documents.lock_registry(text) TO rac_user,rac_match,rac_chat;
