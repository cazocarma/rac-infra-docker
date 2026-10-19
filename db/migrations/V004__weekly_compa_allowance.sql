SET search_path TO public;
-- One durable record per confirmed booking, retained after late cancellations.
CREATE TABLE sesion_cupo_semanal (
  sesion_id UUID PRIMARY KEY REFERENCES sesion(id) ON DELETE CASCADE,
  compa_id UUID NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
  semana DATE NOT NULL,
  consumido_en TIMESTAMPTZ NOT NULL DEFAULT now(),
  restituido_en TIMESTAMPTZ
);
CREATE INDEX idx_cupo_compa_semana ON sesion_cupo_semanal(compa_id, semana) WHERE restituido_en IS NULL;
INSERT INTO sesion_cupo_semanal(sesion_id,compa_id,semana)
SELECT id,compa_id,date_trunc('week',fecha_inicio AT TIME ZONE 'America/Santiago')::date
FROM sesion WHERE estado IN ('activa','finalizada');
-- Only a future verified payment integration may create subscription entitlements.
-- No activation endpoint, demo subscriptions or simulated charges are provided.
CREATE TABLE compa_suscripcion (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  compa_id UUID NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
  referencia_externa TEXT UNIQUE NOT NULL,
  estado TEXT NOT NULL CHECK (estado IN ('activa','cancelada')),
  inicio TIMESTAMPTZ NOT NULL,
  fin TIMESTAMPTZ NOT NULL,
  creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (fin > inicio)
);
CREATE INDEX idx_suscripcion_compa ON compa_suscripcion(compa_id,inicio,fin) WHERE estado='activa';
