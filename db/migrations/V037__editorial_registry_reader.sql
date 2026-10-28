-- A private, minimal head read for the staff CAS confirmation. Does not expose
-- documents, answer keys, audit subjects or direct table grants to the login.
CREATE FUNCTION documents.read_editorial_registry(p_locale text) RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT version FROM documents.head WHERE locale=p_locale
$$;
REVOKE ALL ON FUNCTION documents.read_editorial_registry(text) FROM PUBLIC;
