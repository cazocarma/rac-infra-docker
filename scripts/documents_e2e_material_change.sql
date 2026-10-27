-- Synthetic material change, exclusively for documents_lab.py.
BEGIN;
DO $$ BEGIN
 IF current_database()<>'rac_documents_e2e' OR
    (SELECT version FROM documents.head WHERE locale='es')<>1 OR
    NOT EXISTS(SELECT FROM public.legal_documents WHERE version='browser-synthetic-1') THEN
  RAISE EXCEPTION 'disposable_document_fixture_required';
 END IF;
END $$;
INSERT INTO public.legal_documents(kind,version,locale,content,material_change,legal_review,approved_by,reviewed_at,published_at)
VALUES('privacy','browser-synthetic-2','es',
 'DOCUMENTO SINTÉTICO MODIFICADO. No son términos legales definitivos. Esta nueva versión material debe aceptarse expresamente; la versión anterior permanece en el historial.',
 true,'approved',gen_random_uuid(),now()-interval '2 hours',now()-interval '1 second');
SELECT documents.activate(gen_random_uuid(),1,'es',
 ARRAY(SELECT DISTINCT ON(kind) id FROM public.legal_documents WHERE locale='es' ORDER BY kind,published_at DESC),
 gen_random_uuid(),gen_random_uuid(),ARRAY['Cambio material sintético de privacidad.','Tu historial anterior se conserva.']);
INSERT INTO public.compa_attestation_requirements(locale,registry_version,definition_id)
SELECT 'es',2,id FROM public.compa_attestation_versions WHERE locale='es' AND version='browser-synthetic-1';
COMMIT;
