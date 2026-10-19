-- 0004_seed_compas.sql
-- Crea 5 compas de prueba con perfiles y skills (idempotente).
-- Requiere que 0003_seed_skills.sql haya corrido antes.

DO $$
DECLARE
  rec RECORD;
  v_user   uuid;
  v_perfil uuid;
  v_skill  text;
  v_skill_id uuid;
BEGIN
  -- Conjunto de compas de prueba
  FOR rec IN
    SELECT * FROM (
      VALUES
        ('Compa Kara',   'compa1@demo.local', 'Fan de karaoke y música',      12000::numeric, 4.5::numeric, ARRAY['karaoke','musica']::text[]),
        ('Compa Asador', 'compa2@demo.local', 'Maestro parrillero y viajes',  18000::numeric, 4.8::numeric, ARRAY['asado','viajes']::text[]),
        ('Compa Cine',   'compa3@demo.local', 'Cine y lectura',               14000::numeric, 4.2::numeric, ARRAY['cine','lectura']::text[]),
        ('Compa Gamer',  'compa4@demo.local', 'Videojuegos y deportes',       16000::numeric, 4.6::numeric, ARRAY['videojuegos','deportes']::text[]),
        ('Compa Runner', 'compa5@demo.local', 'Running y música',             13000::numeric, 4.1::numeric, ARRAY['running','musica']::text[])
    ) AS t(nombre, correo, descripcion, tarifa_hora, rating_promedio, skills)
  LOOP
    -- 1) Upsert de usuario (rol=compa)
    INSERT INTO usuario (id, nombre, correo, rol, keycloak_id, verificado)
    VALUES (gen_random_uuid(), rec.nombre, rec.correo, 'compa', 'kc-'||md5(rec.correo), true)
    ON CONFLICT (correo) DO UPDATE SET
      nombre = EXCLUDED.nombre
    RETURNING id INTO v_user;

    IF v_user IS NULL THEN
      SELECT id INTO v_user FROM usuario WHERE correo = rec.correo;
    END IF;

    -- 2) Upsert de perfil del compa
    INSERT INTO compa_perfil (id, usuario_id, descripcion, tarifa_hora, rating_promedio, disponibilidad_json, foto_url)
    VALUES (gen_random_uuid(), v_user, rec.descripcion, rec.tarifa_hora, rec.rating_promedio, '{}'::jsonb, NULL)
    ON CONFLICT (usuario_id) DO UPDATE SET
      descripcion     = EXCLUDED.descripcion,
      tarifa_hora     = EXCLUDED.tarifa_hora,
      rating_promedio = EXCLUDED.rating_promedio
    RETURNING id INTO v_perfil;

    IF v_perfil IS NULL THEN
      SELECT id INTO v_perfil FROM compa_perfil WHERE usuario_id = v_user;
    END IF;

    -- 3) Vincular skills (si existen en tabla skill)
    IF rec.skills IS NOT NULL THEN
      FOREACH v_skill IN ARRAY rec.skills
      LOOP
        SELECT id INTO v_skill_id FROM skill WHERE name = v_skill;
        IF v_skill_id IS NOT NULL THEN
          INSERT INTO compa_perfil_skill (perfil_id, skill_id)
          VALUES (v_perfil, v_skill_id)
          ON CONFLICT DO NOTHING;
        END IF;
      END LOOP;

      -- Recalcular cache de habilidades del perfil
      PERFORM refresh_habilidades_cache(v_perfil);
    END IF;
  END LOOP;
END $$;
