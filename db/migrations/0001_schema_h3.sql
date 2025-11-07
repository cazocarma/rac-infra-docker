-- 0001_schema_h3.sql
-- Esquema base + normalización de skills para H3

-- Extensiones
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- para gen_random_uuid()

-- ====== Tipos ======
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'rol_enum') THEN
    CREATE TYPE rol_enum AS ENUM ('cliente','compa','admin');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sesion_estado_enum') THEN
    CREATE TYPE sesion_estado_enum AS ENUM ('pendiente','activa','finalizada','cancelada');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'pago_estado_enum') THEN
    CREATE TYPE pago_estado_enum AS ENUM ('pendiente','pagado','fallido');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'pago_metodo_enum') THEN
    CREATE TYPE pago_metodo_enum AS ENUM ('simulado','tarjeta','transferencia');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'reporte_tipo_enum') THEN
    CREATE TYPE reporte_tipo_enum AS ENUM ('incidente','cancelacion','emergencia');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'reporte_estado_enum') THEN
    CREATE TYPE reporte_estado_enum AS ENUM ('pendiente','en_revision','cerrado');
  END IF;
END $$;

-- ====== Tablas principales ======
CREATE TABLE IF NOT EXISTS usuario (
  id UUID PRIMARY KEY,
  nombre VARCHAR(120) NOT NULL,
  correo VARCHAR(180) UNIQUE NOT NULL,
  rol rol_enum NOT NULL,
  keycloak_id VARCHAR(64) UNIQUE NOT NULL,
  verificado BOOLEAN NOT NULL DEFAULT FALSE,
  fecha_registro TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS compa_perfil (
  id UUID PRIMARY KEY,
  usuario_id UUID NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
  descripcion TEXT,
  tarifa_hora NUMERIC(10,2) NOT NULL DEFAULT 0,
  rating_promedio NUMERIC(3,2) NOT NULL DEFAULT 0,
  ubicacion geometry(Point, 4326),
  disponibilidad_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  foto_url TEXT,
  -- cache opcional (no es la fuente de verdad)
  habilidades_cache TEXT[] NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_compa_perfil_usuario ON compa_perfil(usuario_id);
CREATE INDEX IF NOT EXISTS idx_compa_perfil_ubicacion ON compa_perfil USING GIST(ubicacion);
CREATE INDEX IF NOT EXISTS idx_compa_perfil_cache ON compa_perfil USING GIN(habilidades_cache);

-- ====== Normalización de Skills ======
CREATE TABLE IF NOT EXISTS skill (
  id UUID PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_name ON skill(LOWER(name));

CREATE TABLE IF NOT EXISTS compa_perfil_skill (
  perfil_id UUID NOT NULL REFERENCES compa_perfil(id) ON DELETE CASCADE,
  skill_id  UUID NOT NULL REFERENCES skill(id) ON DELETE CASCADE,
  PRIMARY KEY (perfil_id, skill_id)
);

-- ====== Cache de habilidades (trigger) ======
CREATE OR REPLACE FUNCTION refresh_habilidades_cache(p_perfil UUID) RETURNS void AS $$
DECLARE
  arr TEXT[];
BEGIN
  SELECT COALESCE(array_agg(s.name ORDER BY s.name), '{}')
  INTO arr
  FROM compa_perfil_skill cps
  JOIN skill s ON s.id = cps.skill_id
  WHERE cps.perfil_id = p_perfil;

  UPDATE compa_perfil SET habilidades_cache = arr WHERE id = p_perfil;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cps_insert ON compa_perfil_skill;
CREATE TRIGGER trg_cps_insert
AFTER INSERT ON compa_perfil_skill
FOR EACH ROW EXECUTE FUNCTION refresh_habilidades_cache(NEW.perfil_id);

DROP TRIGGER IF EXISTS trg_cps_delete ON compa_perfil_skill;
CREATE TRIGGER trg_cps_delete
AFTER DELETE ON compa_perfil_skill
FOR EACH ROW EXECUTE FUNCTION refresh_habilidades_cache(OLD.perfil_id);

DROP TRIGGER IF EXISTS trg_cps_update ON compa_perfil_skill;
CREATE TRIGGER trg_cps_update
AFTER UPDATE ON compa_perfil_skill
FOR EACH ROW EXECUTE FUNCTION refresh_habilidades_cache(NEW.perfil_id);

-- ====== (Opcional) Tablas adicionales ya previstas en H2/H4+ ======
-- Se agregan aquí sólo si aún no existen en tu base.
CREATE TABLE IF NOT EXISTS sesion (
  id UUID PRIMARY KEY,
  cliente_id UUID NOT NULL REFERENCES usuario(id),
  compa_id UUID NOT NULL REFERENCES usuario(id),
  fecha_inicio TIMESTAMPTZ NOT NULL,
  fecha_fin TIMESTAMPTZ NOT NULL,
  estado sesion_estado_enum NOT NULL,
  monto_total NUMERIC(10,2) NOT NULL DEFAULT 0,
  calificacion_cliente INT,
  calificacion_compa INT
);
CREATE INDEX IF NOT EXISTS idx_sesion_cliente ON sesion(cliente_id);
CREATE INDEX IF NOT EXISTS idx_sesion_compa ON sesion(compa_id);
CREATE INDEX IF NOT EXISTS idx_sesion_estado ON sesion(estado);

CREATE TABLE IF NOT EXISTS mensaje (
  id UUID PRIMARY KEY,
  sesion_id UUID NOT NULL REFERENCES sesion(id) ON DELETE CASCADE,
  remitente_id UUID NOT NULL REFERENCES usuario(id),
  contenido TEXT NOT NULL,
  enviado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mensaje_sesion ON mensaje(sesion_id);

CREATE TABLE IF NOT EXISTS pago (
  id UUID PRIMARY KEY,
  sesion_id UUID NOT NULL REFERENCES sesion(id) UNIQUE ON DELETE CASCADE,
  monto NUMERIC(10,2) NOT NULL,
  estado pago_estado_enum NOT NULL,
  metodo pago_metodo_enum NOT NULL,
  fecha_pago TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reporte (
  id UUID PRIMARY KEY,
  sesion_id UUID NOT NULL REFERENCES sesion(id) ON DELETE CASCADE,
  tipo reporte_tipo_enum NOT NULL,
  descripcion TEXT,
  fecha_reporte TIMESTAMPTZ NOT NULL DEFAULT now(),
  estado reporte_estado_enum NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reporte_sesion ON reporte(sesion_id);
