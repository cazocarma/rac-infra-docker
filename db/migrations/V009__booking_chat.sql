SET search_path TO public;
-- Reuse the original message table; preserve any historical messages.
ALTER TABLE mensaje ALTER COLUMN id SET DEFAULT gen_random_uuid();
ALTER TABLE mensaje ADD COLUMN numero BIGINT GENERATED ALWAYS AS IDENTITY;
ALTER TABLE mensaje ADD COLUMN envio_id UUID;
CREATE UNIQUE INDEX mensaje_numero ON mensaje(numero);
CREATE UNIQUE INDEX mensaje_envio ON mensaje(sesion_id, remitente_id, envio_id);
CREATE INDEX mensaje_historial ON mensaje(sesion_id, numero DESC);
CREATE INDEX mensaje_remitente ON mensaje(remitente_id);
ALTER TABLE mensaje ADD CONSTRAINT mensaje_texto_valido
  CHECK (char_length(btrim(contenido)) BETWEEN 1 AND 2000) NOT VALID;
CREATE FUNCTION validar_mensaje_reserva() RETURNS trigger AS $$
DECLARE reserva sesion%ROWTYPE;
BEGIN
  SELECT * INTO reserva FROM sesion WHERE id=NEW.sesion_id FOR SHARE;
  IF NOT FOUND OR reserva.estado <> 'activa'
     OR NEW.remitente_id NOT IN (reserva.cliente_id, reserva.compa_id) THEN
    RAISE EXCEPTION 'chat_not_available' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = public;
CREATE TRIGGER mensaje_reserva BEFORE INSERT ON mensaje
FOR EACH ROW EXECUTE FUNCTION validar_mensaje_reserva();
