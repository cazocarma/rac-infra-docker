-- 0003_seed_skills.sql
-- Carga de habilidades base (idempotente)

INSERT INTO skill (id, name) VALUES
  (gen_random_uuid(), 'karaoke'),
  (gen_random_uuid(), 'asado'),
  (gen_random_uuid(), 'cine'),
  (gen_random_uuid(), 'running')
ON CONFLICT (name) DO NOTHING;
