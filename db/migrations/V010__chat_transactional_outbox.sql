SET search_path TO public;
-- Freeze message writes while the historical stream is established. Flyway
-- keeps this lock until the migration and trigger creation commit together.
LOCK TABLE mensaje IN SHARE ROW EXCLUSIVE MODE;
CREATE TABLE chat_cursor (
  sesion_id UUID PRIMARY KEY REFERENCES sesion(id) ON DELETE CASCADE,
  version BIGINT NOT NULL CHECK (version > 0)
);
CREATE TABLE chat_outbox (
  sesion_id UUID NOT NULL REFERENCES sesion(id) ON DELETE CASCADE,
  version BIGINT NOT NULL CHECK (version > 0),
  mensaje_id UUID NOT NULL UNIQUE REFERENCES mensaje(id) ON DELETE CASCADE,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (sesion_id, version)
);
INSERT INTO chat_outbox(sesion_id,version,mensaje_id,creado_en)
SELECT sesion_id,row_number() OVER (PARTITION BY sesion_id ORDER BY numero),id,enviado_en
FROM mensaje;
INSERT INTO chat_cursor(sesion_id,version)
SELECT sesion_id,max(version) FROM chat_outbox GROUP BY sesion_id;

CREATE FUNCTION encolar_mensaje_chat() RETURNS trigger AS $$
DECLARE siguiente BIGINT;
BEGIN
  -- Row locking on this per-booking counter orders commits, not just sequence
  -- allocation. A reconnect cursor cannot skip a slower concurrent commit.
  INSERT INTO chat_cursor(sesion_id,version) VALUES(NEW.sesion_id,1)
  ON CONFLICT (sesion_id) DO UPDATE SET version=chat_cursor.version+1
  RETURNING version INTO siguiente;
  INSERT INTO chat_outbox(sesion_id,version,mensaje_id)
  VALUES(NEW.sesion_id,siguiente,NEW.id);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = public;
CREATE TRIGGER mensaje_outbox AFTER INSERT ON mensaje
FOR EACH ROW EXECUTE FUNCTION encolar_mensaje_chat();
