SET search_path TO public;
CREATE TABLE chat_bloqueo (
  sesion_id uuid NOT NULL REFERENCES sesion ON DELETE CASCADE,
  usuario_id uuid NOT NULL REFERENCES usuario ON DELETE CASCADE,
  creado_en timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(sesion_id,usuario_id)
);
CREATE INDEX chat_bloqueo_usuario ON chat_bloqueo(usuario_id);
CREATE TABLE chat_reporte (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  sesion_id uuid NOT NULL REFERENCES sesion ON DELETE CASCADE,
  usuario_id uuid NOT NULL REFERENCES usuario ON DELETE CASCADE,
  motivo text NOT NULL CHECK(motivo IN ('acoso','spam','contenido_inapropiado','otro')),
  detalle text NOT NULL CHECK(char_length(btrim(detalle)) BETWEEN 10 AND 1000),
  hasta_numero bigint NOT NULL CHECK(hasta_numero>=0),
  estado text NOT NULL DEFAULT 'abierto' CHECK(estado IN ('abierto','atendido','desestimado')),
  creado_en timestamptz NOT NULL DEFAULT now(),
  UNIQUE(sesion_id,usuario_id)
);
CREATE INDEX chat_reporte_usuario ON chat_reporte(usuario_id);
CREATE INDEX chat_reporte_cola ON chat_reporte(estado,creado_en,id);
CREATE TABLE chat_auditoria (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  reporte_id uuid REFERENCES chat_reporte ON DELETE CASCADE,
  sesion_id uuid NOT NULL REFERENCES sesion ON DELETE CASCADE,
  actor_subject text NOT NULL,
  accion text NOT NULL CHECK(accion IN ('bloquear','desbloquear','reportar','consultar','atendido','desestimado')),
  justificacion text NOT NULL CHECK(char_length(justificacion) BETWEEN 1 AND 1000),
  creado_en timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX chat_auditoria_reporte ON chat_auditoria(reporte_id,id);
CREATE INDEX chat_auditoria_sesion ON chat_auditoria(sesion_id,id);
-- Serialize block changes and message insertion using the booking row first.
CREATE OR REPLACE FUNCTION validar_mensaje_reserva() RETURNS trigger AS $$
DECLARE reserva sesion%ROWTYPE;
BEGIN
  SELECT * INTO reserva FROM sesion WHERE id=NEW.sesion_id FOR SHARE;
  IF NOT FOUND OR reserva.estado <> 'activa'
     OR NEW.remitente_id NOT IN (reserva.cliente_id,reserva.compa_id)
     OR EXISTS(SELECT 1 FROM chat_bloqueo WHERE sesion_id=NEW.sesion_id) THEN
    RAISE EXCEPTION 'chat_not_available' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = public;
