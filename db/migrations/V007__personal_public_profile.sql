SET search_path TO public;

ALTER TABLE usuario ADD COLUMN biografia TEXT NOT NULL DEFAULT ''
  CHECK (char_length(biografia) <= 600);
-- Only server-generated object names; legacy foto_perfil URLs are not trusted.
ALTER TABLE usuario ADD COLUMN foto_clave TEXT
  CHECK (foto_clave ~ '^[a-f0-9]{32}\.jpg$');
