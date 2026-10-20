SET search_path TO public;
CREATE TABLE reserva_resena (
  sesion_id UUID PRIMARY KEY REFERENCES sesion(id) ON DELETE CASCADE,
  cliente_id UUID NOT NULL REFERENCES usuario(id),
  compa_id UUID NOT NULL REFERENCES usuario(id),
  puntuacion SMALLINT NOT NULL CHECK (puntuacion BETWEEN 1 AND 5),
  comentario TEXT NOT NULL DEFAULT '' CHECK (char_length(comentario) <= 1000),
  creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (cliente_id <> compa_id)
);
CREATE INDEX resena_compa_reciente ON reserva_resena(compa_id, creado_en DESC, sesion_id);
CREATE FUNCTION validar_resena_verificada() RETURNS trigger AS $$
DECLARE reserva sesion%ROWTYPE;
BEGIN
  SELECT * INTO reserva FROM sesion WHERE id=NEW.sesion_id FOR SHARE;
  IF NOT FOUND OR reserva.estado <> 'finalizada' OR reserva.fecha_fin > statement_timestamp()
     OR reserva.cliente_id <> NEW.cliente_id OR reserva.compa_id <> NEW.compa_id THEN
    RAISE EXCEPTION 'review_not_eligible' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = public;
CREATE TRIGGER resena_verificada BEFORE INSERT OR UPDATE ON reserva_resena
FOR EACH ROW EXECUTE FUNCTION validar_resena_verificada();
