-- The user service owns profile-to-skill associations. Replacing a profile's
-- skills deletes its previous associations inside the onboarding transaction.
-- Keep this permission scoped to that owner and that join table.
GRANT DELETE ON public.compa_perfil_skill TO rac_user;
