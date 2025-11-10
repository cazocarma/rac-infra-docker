-- 0003_seed_skills.sql
-- Carga de habilidades base (idempotente)

INSERT INTO skill (id, name) VALUES
  (gen_random_uuid(), 'karaoke'),
  (gen_random_uuid(), 'asado'),
  (gen_random_uuid(), 'cine'),
  (gen_random_uuid(), 'running'),
  (gen_random_uuid(), 'videojuegos'),
  (gen_random_uuid(), 'lectura'),
  (gen_random_uuid(), 'viajes'),
  (gen_random_uuid(), 'musica'),
  (gen_random_uuid(), 'deportes')
ON CONFLICT (name) DO NOTHING;
