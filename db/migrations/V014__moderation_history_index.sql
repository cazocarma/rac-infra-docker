SET search_path TO public;
-- Per-state pages already use chat_reporte_cola(estado,creado_en,id).
-- This index supports the cross-state chronological history and keyset cursor.
CREATE INDEX chat_reporte_historial ON chat_reporte(creado_en,id);
