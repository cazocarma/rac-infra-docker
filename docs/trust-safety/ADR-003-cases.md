# ADR-003 — Reportes, casos, acciones y apelaciones unificados

Estado: dirección técnica aprobada; D02/D06/D07/D10 pendientes.

## Dueños y autorización

Admin incorporará el dominio T&S y esquema/rol propios para reports, cases, case_reports, case_events, actions, appeals y accesos sensibles. Esto amplía su responsabilidad actual de agregación y debe aprobarse; no permite escribir directamente las tablas de negocio de otro dueño. User mantiene standing, match reservas, chat mensajes. Los efectos se piden por comandos autenticados, versionados e idempotentes.

Reportes contra usuario, revisión, foto, reseña, conversación o reserva. Objetivo tipado y snapshot fijado al recibir; descripción opcional cifrada de hasta 1000 caracteres. Un índice parcial impide más de un reporte abierto por reportante/objetivo, incluidos reintentos concurrentes. Agrupar casos por sujeto según política, no mezclar automáticamente identidades por una señal débil. `case_events` es append-only y registra asignación, cambio de severidad y actuación.

AccessGuard combina rol, MFA/step-up verificable, asignación/propósito, conflicto de interés y justificación temporal ligada a sujeto/caso/alcance. Auditoría duradera antes de entregar contenido. Una descripción de reporte también es privada. Ni `admin` comercial ni `ts_agent` reciben acceso general a chats. Participantes conservan su acceso legítimo según la reserva; el acceso staff solo ve el contexto evidenciado y autorizado. El token de servicio no sustituye la identidad del actor delegado.

Roles de consola: ts_agent, ts_lead, legal, support, business_admin, sin heredar del admin actual. Verificar ACR/amr y antigüedad de autenticación; no basta tener rol o estar matriculado en MFA. Políticas y permisos negativos se prueban antes de exponer la consola. Sin autoasignación de caso propio ni revisión de apelación por quien decidió la acción.

## Triaje y decisiones

P0 menores/peligro inminente; P1 drogas/servicios sexuales/violencia/armas; P2 fraude/acoso/suplantación/desvío; P3 restante. SLA propuesto 1/24/72/168 h, sujeto a responsable y cobertura. Alertas por falta de asignación no prometen respuesta de emergencia. D06 debe resolver si un reporte sin corroboración puede ocultar una publicación: mitigar denuncias coordinadas sin perder urgencia. P0 admite medidas preventivas reversibles; no ban automático.

Acciones con razón, versión de política, duración y aviso versionado; nota interna cifrada fuera de logs. Ban necesita dos revisores autorizados distintos. En BD: campos requeridos `NOT NULL`, FK válidas y `CHECK (proposed_by <> approved_by)`, además de verificación de permisos y versión al aprobar. Un CHECK nullable solo no asegura cuatro ojos. Ejecutar una única vez aunque se repita el webhook/comando.

Revocar crea otra acción y evento enlazado; no reescribe la decisión histórica. Apelación única por acción con revisor diferente; plazo propuesto 30 días pendiente revisión. No restablece automáticamente reservas, pagos ni publicaciones invalidadas por otras razones. Avisos precisan alcance, regla pública, duración y vía de apelación sin revelar reportante ni léxico privado.

## Corte del reporte de chat

1. Inventariar `chat_reporte`, `chat_auditoria` y `reporte` histórico: conteos, IDs, estados, actores y límites de contexto, sin exportar contenido a logs.
2. Preparar snapshot/evidence port y AccessGuard antes del backfill. Preservar `hasta_version` y `hasta_numero_legacy`; nunca ampliar el límite para facilitar una migración.
3. Backfill bajo rol temporal mínimo, cifrando descripciones y conservando procedencia/IDs de origen. Registrar evidencia histórica como importada, no como capturada originalmente con WORM o cadena inexistentes.
4. Congelar escrituras brevemente; drenar trabajo; verificar conteos, hashes/manifiesto y accesos. Cambiar contratos, UI y APIs juntos. Retirar endpoints de reporte/moderación de chat reemplazados, tablas/triggers y permisos antiguos en la misma serie. No dual-write permanente ni flags legacy.
5. Preservar la historia necesaria antes de eliminar FKs con CASCADE. Copia cifrada de recuperación con política de retención aprobada; si hay error, restauración coordinada en ventana sin permitir escrituras divergentes.

Pruebas: reporte a objetivo ajeno permitido solo según contrato público, lectura privada denegada; IDs manipulados; acceso fuera del límite; duplicación; actor propio; ban unilateral; apelación independiente; reconciliación completa del backfill. Eliminar tablas solo tras validación, no por asumir que son demos.
