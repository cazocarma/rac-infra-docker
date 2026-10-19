SET search_path TO public;
-- Preserve the interpretation of all existing weekly windows.
ALTER TABLE compa_availability ADD COLUMN zona_horaria TEXT NOT NULL DEFAULT 'UTC'
  CHECK (length(zona_horaria) BETWEEN 1 AND 100);
