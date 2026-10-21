# Chat privado por reserva — API y recuperación de eventos

Fecha: 2026-10-20.

`rac-chat-service` implementa una API de mensajes de texto vinculados a reservas y autenticados con OIDC. Su README documenta contrato y configuración.

## Reglas

Solo los dos participantes pueden acceder. Una reserva activa permite enviar; finalizada o cancelada conserva el historial en solo lectura. Una pendiente no habilita chat. El administrador no tiene permiso implícito para leer conversaciones ajenas. Los envíos usan UUID del cliente para reintentos sin duplicados. Todavía no hay adjuntos, sockets, push, edición, borrado ni confirmaciones de lectura.

## Migración V009

Reutiliza `public.mensaje`, existente en V001, sin copiar ni eliminar historial. Agrega `numero` (orden/cursor bigint), `envio_id` e índices. El límite de texto se aplica a nuevos envíos; `NOT VALID` evita rechazar la migración por mensajes históricos incompatibles con ese límite. El trigger verifica estado y remitente contra la reserva bloqueada con FOR SHARE, impidiendo que una cancelación se intercale entre validación y commit.

La tabla ya queda incluida en los respaldos de PostgreSQL; no se agrega un volumen ni bucket. La copia fuera del PC se deja para otra iteración.

## Entrega y validación

Se entregan PR de API y PR de esquema hacia `main`. Son dependientes: aplicar V009 y V010 antes de ejecutar el backend nuevo. El pipeline propio de chat prueba Go y PostgreSQL 16. El runner de migraciones de infra ejecuta también las pruebas contra las migraciones reales cuando encuentra el repositorio hermano actualizado. La integración alojada incorpora los cinco servicios con revisiones fijadas.

## Integración incorporada

1. Listado paginado de conversaciones del usuario.
2. Incorporar chat a manifiestos de release, preflight, Compose y observabilidad, conservando promoción por imágenes inmutables y revisando acceso de CI al quinto repositorio.
3. Conectar Mensajes y accesos desde reservas en Flutter, con actualización, reintentos y estados vacíos/error/solo lectura en mobile y web.
4. Probar dos identidades reales por OIDC en navegador antes de habilitar el menú.

**Mensajes ya tiene interfaz y backend en DEV**. El servicio se levanta con Compose; QA/PRD siguen sin host y requieren cinco imágenes inmutables.


## Outbox y reconexión (V010)

Cada inserción de mensaje genera un evento mediante trigger dentro de la misma transacción. Si falla el evento, se revierte el mensaje. La tabla `chat_outbox` solo guarda referencias, versión por reserva y hora de servidor; no duplica el texto. No se mantiene una cola en RAM ni se depende de RabbitMQ para este recorrido.

`chat_cursor` serializa la asignación de versiones por reserva hasta el commit. Una secuencia global o el número del mensaje no bastan: dos transacciones pueden confirmar en otro orden y un cursor ingenuo omitiría la primera. V010 bloquea escrituras de mensaje durante la migración para incorporar historial existente y crear el trigger de forma atómica. En una BD grande se debe planificar esa ventana.

El canal es HTTP long polling autenticado: `GET /api/chat/bookings/{id}/events?after=0&wait=25`. Devuelve hasta 50 referencias, `cursor`, `has_more` y `can_send`. Las consultas usan un snapshot consistente y se repiten cada 500 ms, liberando la transacción y conexión de BD entre consultas. No requiere afinidad con una instancia: otra instancia recupera los mismos eventos desde PostgreSQL. Límite actual por proceso: 100 consultas simultáneas y cuatro por identidad. Un 429 incluye Retry-After; el cliente debe aplicar espera y jitter.

La lectura del historial incluye `event_cursor` del mismo snapshot que sus mensajes. Procedimiento del cliente:

1. Cargar historial y conservar su `event_cursor` como punto de partida.
2. Esperar eventos a partir de ese cursor usando Bearer en encabezado, nunca en URL.
3. Ante eventos, fusionar el mensaje incluido por ID y avanzar el cursor solo tras procesarlos. Para historial antiguo usar la paginación `before`.
4. Reabrir inmediatamente cuando haya otra página. Ante desconexión o 503, reintentar con backoff/jitter y el último cursor procesado. Un evento puede repetirse; deduplicar por ID.
5. Ante 401 renovar sesión o volver a ingresar; ante 404 cerrar la conversación. Ante `cursor_ahead` volver al snapshot inicial. Una reserva en solo lectura no necesita mantener un poll vacío continuo.

Los permisos se comprueban en cada consulta y el poll termina al vencer el token. La revocación anticipada de un JWT no se comprueba mediante introspección: los roles del token siguen sujetos a su vigencia. El canal ofrece replay al menos una vez; no hay confirmación de lectura, ni una bandera global que elimine eventos al atender al primer dispositivo.

## Pruebas reproducibles

Desde infra ejecutar `python scripts/test_migrations.py` con Docker activo y el repositorio chat hermano actualizado. Solo crea recursos desechables. Prueba migraciones reales, inserción atómica, fallo inyectado al escribir outbox, reintentos concurrentes, reconexión con respuesta perdida y nueva instancia HTTP, commit lento bloqueando un segundo evento, cierre por desconexión/vencimiento y límites de conexiones. Esto no simula pérdida física del disco ni reemplaza el ensayo de restauración.

El CI propio de chat obtiene V010 del repo público infra mediante checkout a un SHA fijo, ejecuta esa migración en su schema desechable y prueba el canal con PostgreSQL 16. El pin hace reproducible el contrato productor/consumidor aunque cambien las ramas.

## Alcance de privacidad y evidencia

Este outbox es un mecanismo de entrega recuperable, no un registro forense inalterable. Los roles actuales de BD siguen siendo privilegiados y compartidos; no hay todavía almacenamiento de auditoría independiente ni sellado de tiempo externo. La hora del servidor y el usuario autenticado no prueban por sí solos qué persona física escribió.

Antes de usuarios reales: acordar retención/eliminación y preservación por incidentes con asesoría jurídica; separar roles de BD, configurar TLS y cifrado en reposo del host y establecer respuesta a incidentes. El acceso excepcional de administrador se limita ahora a reportes abiertos, con justificación y auditoría; ver [moderación](moderacion-chat.md). No se agregan plazos de retención arbitrarios. Los logs operativos conservan rutas parametrizadas y estados, sin tokens ni cuerpos de mensajes. La copia fuera del PC continúa diferida; no hay garantía de recuperación si se pierde ese equipo.


## Recorrido integrado en DEV

- Mensajes lista conversaciones de reservas confirmadas/cerradas; Mis reservas también permite abrirlas.
- El historial inicial trae su cursor; los eventos autenticados incluyen el mensaje original mediante JOIN, evitando perder mensajes intermedios por consultar solo los 50 últimos.
- Flutter combina por id, conserva la clave de un envío incierto, reconoce un envío ya guardado por envio_id, y renueva una vez la sesión ante un 401. El borrador queda solo en memoria de esa pantalla; cerrar/recargar la página no lo conserva.
- El canal se cierra al ocultar/cerrar la app y se recupera por cursor al volver. Los errores transitorios aplican backoff/jitter. Historial anterior se carga por páginas sin avanzar el cursor de eventos.
- Cancelar/finalizar conserva el historial y retira el editor. Los bloqueos también detienen los mensajes nuevos. La revisión administrativa se limita a reportes abiertos con justificación y auditoría; ver [moderación](moderacion-chat.md). No hay adjuntos, indicadores de lectura ni notificaciones push.
- NGINX usa un timeout de 40 segundos para polls de hasta 25; el servicio no publica puerto directo. Prometheus lo observa por la red interna. Los tokens solo viajan en Authorization.

Los manifiestos de release ahora requieren CHAT_IMAGE, además de AUTH/USER/MATCH/FRONTEND. Los releases incompletos fallan antes del despliegue. El CI de infra clona los cinco repositorios a los commits de ci/companion-revisions.json y comprueba su acceso mediante el token temporal de la GitHub App. Actualizar ese archivo mediante PR al integrar nuevas versiones; las ramas móviles no cambian silenciosamente el conjunto probado.

Prueba integrada: python scripts/test_chat_browser.py con Playwright/Chromium y DEV levantado. Crea un comprador de prueba, usa el compa demo solo para una reserva propiedad del fixture y elimina sus datos al terminar. Comprueba dos sesiones reales de Keycloak, mensajes en ambas direcciones, pérdida/restablecimiento de red, historial persistido, vista mobile/web y cierre por cancelación. Artefactos en RAC_BROWSER_ARTIFACTS.
