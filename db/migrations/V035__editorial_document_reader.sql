-- Read an exact editorial revision for authenticated legal review. No list of
-- private user data, no role grants and no automatic workflow activation.
CREATE FUNCTION documents.read_editorial_document(p_id uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object(
  'id',d.id,'kind',d.kind,'version',d.version,'locale',d.locale,
  'content',d.content,'sha256',encode(d.content_sha256,'hex'),
  'material_change',d.material_change,'author_id',e.author_id,
  'drafted_at',e.drafted_at,'decision',r.decision,'reviewer_id',r.reviewer_id,
  'reviewed_at',r.reviewed_at,'published_at',d.published_at)
 FROM public.legal_documents d JOIN documents.editorial_revision e ON e.document_id=d.id
 LEFT JOIN documents.editorial_review r ON r.document_id=d.id
 WHERE d.id=p_id
$$;
REVOKE ALL ON FUNCTION documents.read_editorial_document(uuid) FROM PUBLIC;

-- Own-principal readiness only. No API caller supplies another identity.
CREATE FUNCTION documents.editorial_ready() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT EXISTS(SELECT FROM audit.writer_principals p JOIN audit.chain_heads h ON h.chain_id=p.chain_id
 WHERE p.database_role=session_user)
$$;
REVOKE ALL ON FUNCTION documents.editorial_ready() FROM PUBLIC;
