-- P06/M3. A closed activity catalog replaces free-text skills: what is not in
-- the list cannot be offered. The seeded list is the prompt's proposal and
-- stays approval='proposed' until D04 approves activities and places; runtime
-- serves proposed entries only in dev/test. Absence defines what is forbidden
-- (no health, massage, transport, care of children or dependants, alcohol or
-- private parties, or generic "company").
SET LOCAL lock_timeout = '2s';

CREATE TABLE public.activity_categories (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z][a-z0-9_]{1,47}$'),
 name_key text NOT NULL CHECK (name_key ~ '^activity[A-Z][A-Za-z0-9]{1,63}$'),
 description_key text NOT NULL CHECK (description_key ~ '^activity[A-Z][A-Za-z0-9]{1,63}$'),
 status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','retired')),
 approval text NOT NULL DEFAULT 'proposed' CHECK (approval IN ('proposed','approved')),
 min_age int NOT NULL DEFAULT 18 CHECK (min_age >= 18),
 setting text NOT NULL CHECK (setting IN ('public_place','venue','online','private_place')),
 requires_additional_verification boolean NOT NULL DEFAULT false,
 sort int NOT NULL
);

INSERT INTO public.activity_categories(slug,name_key,description_key,setting,sort) VALUES
 ('cine','activityCinema','activityCinemaDescription','venue',10),
 ('teatro','activityTheatre','activityTheatreDescription','venue',20),
 ('conciertos','activityConcerts','activityConcertsDescription','venue',30),
 ('museos','activityMuseums','activityMuseumsDescription','venue',40),
 ('running','activityRunning','activityRunningDescription','public_place',50),
 ('trekking','activityTrekking','activityTrekkingDescription','public_place',60),
 ('ciclismo','activityCycling','activityCyclingDescription','public_place',70),
 ('juegos_de_mesa','activityBoardGames','activityBoardGamesDescription','venue',80),
 ('karaoke','activityKaraoke','activityKaraokeDescription','venue',90),
 ('conversacion_idiomas','activityLanguageExchange','activityLanguageExchangeDescription','public_place',100),
 ('fotografia_urbana','activityStreetPhotography','activityStreetPhotographyDescription','public_place',110),
 ('gastronomia','activityRestaurants','activityRestaurantsDescription','venue',120);

CREATE TABLE public.compa_activities (
 -- Activities belong to the profile: removing the profile removes them.
 compa_id uuid NOT NULL REFERENCES public.compa_perfil(id) ON DELETE CASCADE,
 category_id uuid NOT NULL REFERENCES public.activity_categories(id),
 note text CHECK (char_length(note) BETWEEN 1 AND 140),
 created_at timestamptz NOT NULL DEFAULT statement_timestamp(),
 PRIMARY KEY (compa_id, category_id)
);
CREATE INDEX compa_activities_category ON public.compa_activities (category_id, compa_id);

-- Skills that map to no category are kept for review and never published;
-- they are not deleted on the assumption that DEV holds no real data.
CREATE TABLE public.legacy_compa_skills (
 compa_id uuid NOT NULL REFERENCES public.compa_perfil(id) ON DELETE CASCADE,
 name text NOT NULL,
 migrated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
 PRIMARY KEY (compa_id, name)
);

-- Exact, case- and accent-insensitive name matches only. Similar-sounding
-- skills (e.g. "musica", "asado") stay for review instead of being guessed.
-- No temporary tables: the deployed migrator has no TEMP privilege.
INSERT INTO public.compa_activities(compa_id,category_id)
SELECT DISTINCT cps.perfil_id, c.id
FROM public.compa_perfil_skill cps
JOIN public.skill s ON s.id = cps.skill_id
JOIN (VALUES
 ('cine','cine'),('teatro','teatro'),('conciertos','conciertos'),('museos','museos'),
 ('running','running'),('trekking','trekking'),('ciclismo','ciclismo'),
 ('juegos de mesa','juegos_de_mesa'),('karaoke','karaoke'),
 ('conversacion en idiomas','conversacion_idiomas'),('fotografia urbana','fotografia_urbana'),
 ('gastronomia','gastronomia')) AS m(name, slug)
 ON m.name = translate(lower(btrim(s.name)),'áéíóúüñ','aeiouun')
JOIN public.activity_categories c ON c.slug = m.slug;
INSERT INTO public.legacy_compa_skills(compa_id,name)
SELECT DISTINCT cps.perfil_id, s.name
FROM public.compa_perfil_skill cps
JOIN public.skill s ON s.id = cps.skill_id
WHERE translate(lower(btrim(s.name)),'áéíóúüñ','aeiouun') NOT IN (
 'cine','teatro','conciertos','museos','running','trekking','ciclismo','juegos de mesa',
 'karaoke','conversacion en idiomas','fotografia urbana','gastronomia');

-- Retire every free-text skill surface in the same cut; no old columns remain.
DROP TRIGGER IF EXISTS trg_cps_refresh ON public.compa_perfil_skill;
DROP FUNCTION IF EXISTS public.trg_refresh_habilidades_cache();
DROP FUNCTION IF EXISTS public.refresh_habilidades_cache(uuid);
DROP TABLE public.compa_perfil_skill;
DROP TABLE public.skill;
ALTER TABLE public.compa_perfil DROP COLUMN habilidades_cache;

-- User owns the catalog relation; the catalog itself changes only by migration.
GRANT SELECT ON public.activity_categories TO rac_user;
GRANT SELECT, INSERT, DELETE ON public.compa_activities TO rac_user;
GRANT UPDATE (note) ON public.compa_activities TO rac_user;
-- The DEV seed gives demo compas a catalog activity, as it did with skills.
GRANT SELECT ON public.activity_categories TO rac_seed;
GRANT SELECT, INSERT ON public.compa_activities TO rac_seed;
