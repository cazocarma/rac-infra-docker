# ADR-007 — Auditoría encadenada y anclajes independientes

Estado: dirección técnica aprobada; almacenamiento externo y gestión de claves D08/D11/D14 pendientes.

## Garantía buscada

Detectar alteración, reordenamiento y pérdida de eventos con respecto a un anclaje confiable. Un hash encadenado dentro de la misma BD no impide que un DBA reescriba todo ni detecta por sí solo el truncamiento del final. No llamarlo inmutable sin protección adicional comprobada.

`rac-platform/audit` define evento mínimo y canonicalización versionada: actor opaco, acción, sujeto/recurso opaco, propósito codificado, policy_version, case reference, timestamp servidor, chain_id, secuencia, prev_hash y hash. Nunca cuerpo de mensaje, documento, correo, teléfono, descripción del reporte ni justificación libre. La nota se cifra aparte y se referencia. Formato canónico especificado (por ejemplo RFC 8785 con restricciones de números/timestamps); vectores públicos de prueba impiden divergencias entre módulos.

Append serializado mediante bloqueo de cabecera por chain_id y transacción atómica evento+head. La secuencia de cadena no supone que BIGSERIAL no tiene huecos: asignación transaccional definida y testeada con rollback. Eventos de varias cadenas tienen anclajes y génesis explícitos; no se mezclan silenciosamente.

Aplicaciones sin UPDATE/DELETE/TRUNCATE/DDL sobre auditoría. Append mediante función/servicio restringido que verifica identidad autenticada y campos permitidos; no confiar en actor arbitrario del JSON ni dar INSERT amplio a todos los servicios. Migrador separado, credenciales acotadas. El dueño puede auditar cambios en la misma transacción o registrar intención outbox atómica. Para leer evidencia, se exige confirmación duradera de auditoría antes de devolver bytes: si falla, denegar acceso. No usar un log best-effort para afirmar que todo acceso quedó registrado.

Firmar checkpoints de secuencia/head con claves fuera del host y anclarlos en un destino independiente protegido contra reescritura, con frecuencia aprobada. Verificador dispone del último anclaje confiable y alerta ante atraso; intervalos sin anclar tienen riesgo residual explícito. Un superusuario del host aún puede sabotear disponibilidad; no afirmar protección absoluta frente a él. Asegurar recuperación de claves y checkpoints sin meterlos junto al backup mutable único.

`rac-audit verify --from --to` valida canonicalización, firmas, continuidad y enlace con predecesor/anclaje confiable, no solo recalcula el rango pedido. Contra el último anclaje debe detectar edición, inserción, reordenamiento y truncamiento de cola. Un checkpoint diario por sí solo no detecta una cola recién eliminada: registrar y comparar cabezas firmadas fuera del dominio comprometido.

Privacidad: evitar PII en payload canónico; cifrado y supresión de referencias/metadata personales permitidas donde proceda mediante eventos explícitos, sin recalcular silenciosamente la historia. Migrar auditoría antigua con manifiesto de importación; no fingir que estaba encadenada en su fecha original. Validación: concurrencia/rollback, permisos negativos, fallo de append, tamper por DBA en copia de prueba, pérdida de cola, recuperación y supresión autorizada sin romper verificabilidad.
