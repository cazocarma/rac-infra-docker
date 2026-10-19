SET search_path TO public;
ALTER TABLE sesion ADD COLUMN IF NOT EXISTS creado_en TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE sesion ADD COLUMN IF NOT EXISTS actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE EXTENSION IF NOT EXISTS btree_gist;
-- Concurrent reservations must not bypass the availability pre-check.
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_constraint WHERE conname='sesion_no_overlap') THEN
  ALTER TABLE sesion ADD CONSTRAINT sesion_no_overlap EXCLUDE USING gist
  (compa_id WITH =, tstzrange(fecha_inicio,fecha_fin,'[)') WITH &&)
  WHERE (estado IN ('pendiente','activa'));
 END IF;
END $$;
ALTER TABLE sesion DROP CONSTRAINT IF EXISTS sesion_valid_range;
ALTER TABLE sesion ADD CONSTRAINT sesion_valid_range CHECK(fecha_fin>fecha_inicio);
