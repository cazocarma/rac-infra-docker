SET search_path TO public;
CREATE TABLE notificacion (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario_id UUID NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
  sesion_id UUID NOT NULL REFERENCES sesion(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL,
  titulo TEXT NOT NULL,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
  leido_en TIMESTAMPTZ
);
CREATE INDEX idx_notificacion_usuario ON notificacion(usuario_id, creado_en DESC, id DESC);
-- Events are committed with the booking; rolled back transitions produce no alerts.
-- No historical backfill: only new requests and actual state changes notify.
CREATE FUNCTION notificar_reserva() RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
DECLARE titulo_evento TEXT;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.estado = OLD.estado THEN RETURN NEW; END IF;
  END IF;
  titulo_evento := CASE NEW.estado
    WHEN 'pendiente' THEN 'Nueva solicitud de reserva'
    WHEN 'activa' THEN 'Reserva confirmada'
    WHEN 'cancelada' THEN 'Reserva cancelada'
    WHEN 'finalizada' THEN 'Reserva finalizada'
    ELSE 'Reserva actualizada' END;
  INSERT INTO notificacion(usuario_id,sesion_id,tipo,titulo)
  SELECT DISTINCT participante, NEW.id, NEW.estado::text, titulo_evento
  FROM unnest(ARRAY[NEW.cliente_id,NEW.compa_id]) AS participante;
  RETURN NEW;
END;
$$;
CREATE TRIGGER sesion_notificacion AFTER INSERT OR UPDATE OF estado ON sesion
FOR EACH ROW EXECUTE FUNCTION notificar_reserva();
