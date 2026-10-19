SET search_path TO public;
CREATE UNIQUE INDEX IF NOT EXISTS usuario_keycloak_identity ON usuario(keycloak_id);
CREATE INDEX IF NOT EXISTS sesion_cliente_order ON sesion(cliente_id,fecha_inicio DESC);
