SET search_path TO public;
-- Commit the enum addition before V017 uses it.
ALTER TYPE sesion_estado_enum ADD VALUE 'expirada';
