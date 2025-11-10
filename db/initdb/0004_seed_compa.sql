-- 0004_seed_compa.sql
-- Inserta un compa de prueba con perfil y habilidades

INSERT INTO usuario (id, nombre, correo, rol, keycloak_id, verificado)
VALUES (gen_random_uuid(), 'Compa Demo', 'compa@demo.local', 'compa', 'kc-demo-sub', true)
ON CONFLICT (correo) DO NOTHING;

WITH u AS (SELECT id FROM usuario WHERE correo='compa@demo.local')
INSERT INTO compa_perfil (id, usuario_id, descripcion, tarifa_hora, rating_promedio, disponibilidad_json, foto_url)
SELECT gen_random_uuid(), u.id, 'Me gusta karaoke y asados', 15000, 4.7, '{}'::jsonb, NULL
FROM u
ON CONFLICT DO NOTHING;  -- ya no depende de índice unique

DO $$
DECLARE
  v_perfil uuid;
  v_kara uuid;
  v_asado uuid;
BEGIN
  SELECT cp.id INTO v_perfil
  FROM compa_perfil cp JOIN usuario u ON u.id = cp.usuario_id
  WHERE u.correo='compa@demo.local'
  LIMIT 1;

  SELECT id INTO v_kara FROM skill WHERE name='karaoke';
  SELECT id INTO v_asado FROM skill WHERE name='asado';

  IF v_perfil IS NOT NULL THEN
    INSERT INTO compa_perfil_skill (perfil_id, skill_id)
    VALUES (v_perfil, v_kara) ON CONFLICT DO NOTHING;
    INSERT INTO compa_perfil_skill (perfil_id, skill_id)
    VALUES (v_perfil, v_asado) ON CONFLICT DO NOTHING;
    PERFORM refresh_habilidades_cache(v_perfil);
  END IF;
END $$;
