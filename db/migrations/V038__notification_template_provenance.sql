-- Expand only: historical notices retain their exact title and unknown
-- provenance. Never attribute today's catalog to a previously rendered notice.
SET LOCAL lock_timeout = '2s';
ALTER TABLE public.notificacion
 ADD COLUMN template_key text,
 ADD COLUMN template_version text,
 ADD COLUMN template_locale text,
 ADD COLUMN template_legal_review text,
 ADD CONSTRAINT notification_template_provenance_complete CHECK (
  num_nonnulls(template_key,template_version,template_locale,template_legal_review)=0
  OR (
   num_nonnulls(template_key,template_version,template_locale,template_legal_review)=4
   AND template_key ~ '^[a-z][a-z0-9_.]{0,79}$'
   AND template_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
   AND template_locale IN ('es','en')
   AND template_legal_review IN ('pending','approved')
  )
 );
-- Standing delivery has column-level INSERT only. Extend that exact capability
-- without granting access to booking references, reads or updates of notices.
GRANT INSERT(template_key,template_version,template_locale,template_legal_review)
 ON public.notificacion TO rac_standing_alert;
