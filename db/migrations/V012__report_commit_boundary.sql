SET search_path TO public;
-- Identity allocation is not commit order. Keep the legacy value for diagnosis,
-- but fail closed for V011 reports: their original event boundary is unknowable.
ALTER TABLE chat_reporte RENAME COLUMN hasta_numero TO hasta_numero_legacy;
ALTER TABLE chat_reporte ALTER COLUMN hasta_numero_legacy SET DEFAULT 0;
ALTER TABLE chat_reporte ADD COLUMN hasta_version bigint NOT NULL DEFAULT 0
  CHECK(hasta_version>=0);
