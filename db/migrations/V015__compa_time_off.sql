SET search_path TO public;
CREATE TABLE compa_time_off (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 compa_id uuid NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
 desde date NOT NULL, hasta date NOT NULL, zona_horaria text NOT NULL,
 fecha_inicio timestamptz NOT NULL, fecha_fin timestamptz NOT NULL,
 creado_en timestamptz NOT NULL DEFAULT now(),
 CHECK(hasta>=desde AND hasta-desde<366 AND fecha_fin>fecha_inicio),
 UNIQUE(compa_id,desde,hasta,zona_horaria),
 EXCLUDE USING gist(compa_id WITH =,tstzrange(fecha_inicio,fecha_fin,'[)') WITH &&)
);
-- Both sides take the same transaction lock before inspecting the other table.
CREATE FUNCTION guard_time_off() RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.compa_id::text,0));
 IF EXISTS(SELECT 1 FROM sesion WHERE compa_id=NEW.compa_id AND estado IN ('pendiente','activa')
   AND fecha_inicio<NEW.fecha_fin AND fecha_fin>NEW.fecha_inicio) THEN
   RAISE EXCEPTION 'existing_booking' USING ERRCODE='23P01';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_time_off BEFORE INSERT OR UPDATE ON compa_time_off FOR EACH ROW EXECUTE FUNCTION guard_time_off();
CREATE FUNCTION guard_booking_time_off() RETURNS trigger LANGUAGE plpgsql SET search_path=public AS $$
BEGIN
 IF NEW.estado IN ('pendiente','activa') THEN
  PERFORM pg_advisory_xact_lock(hashtextextended(NEW.compa_id::text,0));
  IF EXISTS(SELECT 1 FROM compa_time_off WHERE compa_id=NEW.compa_id AND fecha_inicio<NEW.fecha_fin AND fecha_fin>NEW.fecha_inicio) THEN
   RAISE EXCEPTION 'compa_unavailable' USING ERRCODE='23P01';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_booking_time_off BEFORE INSERT OR UPDATE OF fecha_inicio,fecha_fin,compa_id,estado ON sesion FOR EACH ROW EXECUTE FUNCTION guard_booking_time_off();
