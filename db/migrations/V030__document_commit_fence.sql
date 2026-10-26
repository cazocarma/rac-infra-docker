-- Narrow lock primitive: readers must not receive UPDATE on the registry.
-- Held by the caller transaction until commit/rollback. Activation takes an
-- exclusive head lock, so a checked write and a new registry serialize.
CREATE FUNCTION documents.lock_head(p_locale text) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE current_version bigint;
BEGIN
 SELECT version INTO current_version FROM documents.head WHERE locale=p_locale FOR SHARE;
 IF NOT FOUND OR current_version=0 THEN
  RAISE EXCEPTION 'document_registry_unavailable' USING ERRCODE='55000';
 END IF;
 RETURN current_version;
END $$;
REVOKE ALL ON FUNCTION documents.lock_head(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION documents.lock_head(text) TO rac_user;
