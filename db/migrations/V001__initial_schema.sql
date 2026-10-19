SET search_path TO public;
-- 0010_schema_h3.sql
-- Esquema base normalizado + corrección de triggers

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ===== Tipos =====
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'rol_enum') THEN
    CREATE TYPE rol_enum AS ENUM ('cliente','compa','admin');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'genero_enum') THEN
    CREATE TYPE genero_enum AS ENUM ('masculino','femenino','otro','prefiero_no_decir');
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

-- ===== Tablas principales =====
CREATE TABLE IF NOT EXISTS usuario (
  id UUID PRIMARY KEY,
  nombre VARCHAR(120) NOT NULL,
  correo VARCHAR(180) UNIQUE NOT NULL,
  rol rol_enum NOT NULL,
  keycloak_id VARCHAR(64) UNIQUE NOT NULL,
  verificado BOOLEAN NOT NULL DEFAULT FALSE,
  fecha_registro TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Campos extendidos registro (Hito 4)
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS fecha_nacimiento DATE;
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS genero genero_enum;
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS telefono TEXT;
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS pais TEXT;
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS region TEXT;
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS ciudad TEXT;
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS direccion TEXT;
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS intereses TEXT[];
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS idioma_preferido TEXT;
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS notificaciones_activadas BOOLEAN DEFAULT FALSE;
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS foto_perfil TEXT;
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS ubicacion geometry(Point, 4326);
ALTER TABLE usuario ADD COLUMN IF NOT EXISTS radio_busqueda_km INT;

CREATE TABLE IF NOT EXISTS compa_perfil (
  id UUID PRIMARY KEY,
  usuario_id UUID NOT NULL REFERENCES usuario(id) ON DELETE CASCADE UNIQUE,
  descripcion TEXT,
  tarifa_hora NUMERIC(10,2) NOT NULL DEFAULT 0,
  rating_promedio NUMERIC(3,2) NOT NULL DEFAULT 0,
  ubicacion geometry(Point, 4326),
  disponibilidad_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  foto_url TEXT,
  habilidades_cache TEXT[] NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_compa_perfil_usuario ON compa_perfil(usuario_id);
CREATE INDEX IF NOT EXISTS idx_compa_perfil_ubicacion ON compa_perfil USING GIST(ubicacion);
CREATE INDEX IF NOT EXISTS idx_compa_perfil_cache ON compa_perfil USING GIN(habilidades_cache);

-- ===== Normalización de skills =====
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

-- ===== Cache de habilidades (trigger) =====
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

CREATE OR REPLACE FUNCTION trg_refresh_habilidades_cache() RETURNS trigger AS $$
DECLARE
  v_perfil UUID;
BEGIN
  IF TG_OP = 'DELETE' THEN
    v_perfil := OLD.perfil_id;
  ELSE
    v_perfil := NEW.perfil_id;
  END IF;
  PERFORM refresh_habilidades_cache(v_perfil);
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cps_refresh ON compa_perfil_skill;
CREATE TRIGGER trg_cps_refresh
AFTER INSERT OR UPDATE OR DELETE ON compa_perfil_skill
FOR EACH ROW EXECUTE FUNCTION trg_refresh_habilidades_cache();

-- ===== Otras tablas =====
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
  sesion_id UUID NOT NULL REFERENCES sesion(id) ON DELETE CASCADE,
  monto NUMERIC(10,2) NOT NULL,
  estado pago_estado_enum NOT NULL,
  metodo pago_metodo_enum NOT NULL,
  fecha_pago TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT pago_sesion_unique UNIQUE (sesion_id)
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

-- rac-match-service initial schema



CREATE TABLE IF NOT EXISTS sesion (
  id UUID PRIMARY KEY,
  cliente_id UUID NOT NULL,
  compa_id UUID NOT NULL,
  fecha_inicio TIMESTAMPTZ NOT NULL,
  fecha_fin TIMESTAMPTZ NOT NULL,
  estado sesion_estado_enum NOT NULL DEFAULT 'pendiente',
  monto_total NUMERIC(10,2) NOT NULL DEFAULT 0,
  calificacion_cliente INT,
  calificacion_compa INT,
  creado_en TIMESTAMPTZ DEFAULT now(),
  actualizado_en TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sesion_compa_fecha ON sesion(compa_id, fecha_inicio, fecha_fin);
CREATE INDEX IF NOT EXISTS idx_sesion_cliente_fecha ON sesion(cliente_id, fecha_inicio);

-- Compa availability JSON store
CREATE TABLE IF NOT EXISTS compa_availability (
  compa_id UUID PRIMARY KEY,
  disponibilidad_json JSONB NOT NULL,
  actualizado_en TIMESTAMPTZ DEFAULT now()
);
