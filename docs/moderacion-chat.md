# Bloqueos y reportes del chat

## Responsabilidad y alcance

El servicio de chat conserva la autorización de sus mensajes y los casos asociados. El frontend ofrece Seguridad de la conversación y una cola para cuentas con rol `admin`. El futuro servicio de administración puede coordinar otras áreas consumiendo esta API; no necesita copiar mensajes ni obtener acceso general a su base de datos. Esta entrega no agrega otro microservicio al stack.

Un bloqueo pertenece al participante y a una reserva. Cualquiera detiene los mensajes nuevos de ambos; solo quien creó su bloqueo puede retirarlo. Si ambos bloquean, ambos deben retirarlo para reabrir el canal. La reserva debe seguir activa. El historial permanece accesible a sus participantes. Los bloqueos no cancelan reservas ni cambian cobros o planes.

Reportar es independiente de bloquear. Se admite un reporte por participante y conversación en esta primera entrega; el reintento del mismo contenido devuelve el mismo caso y un contenido distinto devuelve 409. No hay sanción automática. El reporte guarda motivo, descripción y el límite de mensajes existente al crearlo. La revisión no incorpora mensajes enviados después.

## API

Todas las rutas requieren access token OIDC en `Authorization`, con respuesta `no-store`.

| Ruta | Autorización y efecto |
| --- | --- |
| GET `/api/chat/bookings/:id/safety` | Participante; estado agregado, bloqueo propio y `estado_reporte` del reporte propio (`abierto`, `atendido`, `desestimado`, o `null` si no existe). Conserva `reportada` por compatibilidad. No expone el reporte ajeno, justificaciones ni notas internas. |
| POST `/api/chat/bookings/:id/block` | Participante de reserva confirmada/cerrada; `bloqueado` booleano; reintento idempotente. |
| POST `/api/chat/bookings/:id/reports` | Participante; `motivo` entre acoso/spam/contenido_inapropiado/otro y `detalle` de 10–1000 caracteres. |
| GET `/api/chat/moderation/reports?estado=abierto` | Solo admin; filtros abierto/atendido/desestimado/todos y hasta 20 casos por página. Metadatos y fechas, sin descripción, mensajes ni justificaciones. `next_cursor` continúa con `despues`; `offset` queda como compatibilidad. |
| POST `/api/chat/moderation/reports/:id/access` | Solo admin ajeno a la reserva; caso abierto, `justificacion` de 10–500 caracteres, `antes` opcional como cursor decimal string. Registra acceso antes de devolver hasta 50 mensajes. Cada página registra otro acceso. |
| POST `/api/chat/moderation/reports/:id/resolve` | Solo admin ajeno a la reserva que ya registró una consulta; `estado` atendido/desestimado y justificación de 10–1000 caracteres. Actualización y auditoría atómicas. |

El administrador no puede usar los endpoints normales para leer conversaciones ajenas. Tampoco puede revisar ni cerrar su propio caso como moderador. El cierre retira el caso de la cola e impide nuevas consultas por esta API; no retira bloqueos ni borra historial.

## Concurrencia y trazabilidad

V011 crea `chat_bloqueo`, `chat_reporte` y `chat_auditoria`, con índices de cola, usuario y reserva. V012 fija el contexto con la versión transaccional de `chat_cursor` y consulta mediante el outbox, cuyo orden respeta los commits. Una identidad reservada antes pero confirmada después del reporte queda excluida, aunque su número sea menor. Los valores de V011 se conservan en `hasta_numero_legacy`; los reportes previos a V012 mantienen detalle y auditoría, pero reciben contexto cero: no se reconstruye ni amplía retrospectivamente un límite que no se puede garantizar. Las consultas de versiones antiguas fallan al no existir el nombre anterior; desplegar el servicio junto a V012.

Bloqueo, reporte e inserción de mensaje usan primero el lock de la reserva, evitando intercalaciones que permitan escribir después de confirmar un bloqueo. El trigger de mensajes verifica el bloqueo además del estado y remitente. Los eventos reevalúan permisos y devuelven `can_send=false`; el cliente conserva historial y retira el compositor. Tras desbloquear se actualiza la conversación para reabrirlo.

La auditoría guarda subject OIDC, caso/reserva, acción, hora de servidor y justificación. Un fallo al insertar auditoría impide devolver contenido o confirmar la resolución. Los logs operativos no contienen descripciones ni mensajes. No hay exportación ni búsqueda global de conversaciones.

Este registro no es una prueba legal inalterable: los roles de BD actuales siguen siendo compartidos/privilegiados, no hay sellado externo, auditoría fuera del host ni retención acordada. No se promete identidad física del autor ni preservación garantizada. La política de retención, eliminación y preservación por incidentes debe definirse antes de uso real. La copia fuera del PC sigue diferida.

## Validación

Tests de Go con PostgreSQL real: IDOR, bloqueo ajeno, reintento, protección del trigger, historial/eventos en solo lectura, rol de moderación, conflicto de interés, acceso justificado, fallo inyectado de auditoría y cierre. Flutter verifica confirmación de bloqueo, validación de reportes y ausencia de consulta de contenido antes de una acción justificada. El recorrido de navegador complementa estas pruebas con sesiones reales.

La pantalla de seguridad muestra «Pendiente de revisión», «Reporte atendido» o «Reporte desestimado». El botón de actualizar consulta el estado actual; un cierre no habilita un segundo reporte para la misma persona y conversación.

El [historial de moderación](historial-moderacion.md) detalla filtros, paginación estable, privacidad y pruebas.
