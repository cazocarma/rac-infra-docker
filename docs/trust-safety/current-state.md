# Estado real al 2026-10-22

## Evidencia y alcance

Inspección estática de los clones locales. Docker Desktop no respondió: el pipe `DockerDesktopLinuxEngine` no estaba disponible. No se verificaron contenedores, configuración efectiva del realm, datos desplegados ni capacidades de Object Lock en ejecución. Tampoco se comprobó el estado remoto actual de CI. Una configuración en Git no prueba su despliegue.

Los cambios de dashboard inspeccionados están en `feat/admin-dashboard`, con PR abiertos según el estado registrado del trabajo anterior; no se consideran integrados en `main` ni desplegados en producción. No hay servidor productivo identificado.

| Repositorio | HEAD inspeccionado |
|---|---|
| rac-infra-docker | `069eff560e6e398c69e3b793a4321b397209538c` |
| rac-user-service | `e2f544286edab1ad2d671341b3fa7f3c1f39ee7e` |
| rac-match-service | `0bbb14b008b92dba8c2939b2ff3cdc3374419308` |
| rac-chat-service | `b5de7ce56bf0a3299ec37e0ce8a74d4f61883ca0` |
| rac-alert-service | `47460452446b6b0339a059201024f5845bfe524e` |
| rac-admin-service | `f8e46217fdc97d21ffa3b5bfa611885c38bfaed1` |
| rac-frontend-flutter | `422dcc9adadaff4d9f8409cb93aca4bf64202247` |
| rac-shared-contracts | `70a3604a1e624f4e18c510da802daa3716d03217` |
| rac-auth-service | `cdbe0792ad148396cd020a7de6b22076e272ba1d` |
| rac-payment-service | `ebc68fa342de37f91e270d24c834d52ae25699d4` |
| rac-docs | `3b13dc7aeb886bd8db786c1a484e698dec2287b7` |

Atención: `ci/companion-revisions.json` fija auth en `8ab0f75007234ad843788fbe2baa1932b9e94ca9`, distinto del clon local. Las pruebas integradas deben usar un manifiesto coherente y registrar sus SHA. No se debe asumir que prueban automáticamente todos los HEAD locales. La documentación jurídica local previa `docs/descripcion-proyecto-revision-legal.md` permanece fuera de estos cambios.

## Servicios y límites actuales

| Dueño | Endpoints relevantes y fuente | Datos / comportamiento actual |
|---|---|---|
| auth | `cmd/server/main.go`: `GET /api/auth/userinfo` | Expone principal validado; Keycloak hace login. No es autoridad de standing. |
| user | `internal/http/router.go`: `/api/user/compas`, `/compas/:id`, `/skills`, `/compas/:id/reviews`, `/media/profile/:key` públicos; `/me` GET/PUT; `/me/photo` GET/PUT/DELETE; `/me/compa` GET/PUT; POST `/compas`, `/profile`, `/compas/:id/skills`; `/bookings/:id/review` GET/POST; `/admin/summary` GET | Perfil, publicación, foto, habilidades y reseñas. Varias rutas de escritura que deberán cerrarse juntas al introducir revisiones. |
| match | `internal/http/handlers.go`, prefijo `/api/match`: `/availability/:compa_id` GET/POST, `/slots` GET, `/time-off` GET/POST/DELETE por id; `/session` POST; `/session/:id` GET; `/state` PUT; `/extend` POST; listados `/client/:id/sessions`, `/compa/:id/sessions`; `/compa/:id/allowance`; `/admin/summary` | Dueño de reservas, disponibilidad, cupos y suscripción local. Autenticación más controles de rol/propiedad. |
| chat | `internal/http/router.go`, `/api/chat`: conversaciones, mensajes GET/POST, eventos GET, safety GET, block POST, reports POST por reserva; moderación: reports/summary GET, access/resolve POST | Texto persistido, historial y long polling; bloqueo y reportes acotados a contexto anterior al aviso. No hay cifrado de extremo a extremo. |
| alert | `internal/http/router.go`: notifications GET, notifications/:id/read PUT, notifications/read-all PUT | Consume eventos de reservas; bandeja interna. Alias del gateway bajo `/api/user/notifications` requiere inventario de retirada cuando se actualicen consumidores. |
| admin | `internal/http/router.go`: `GET /api/admin/overview` | Agrega resúmenes de los dueños; sin BD propia actual. No es todavía consola T&S ni autoridad de sanciones. |
| payment | `cmd/server/main.go` | Health/readiness/métricas; no negocio de cobros ni webhooks reales. |
| frontend | Flutter web/móvil | Flujos de perfil, reserva, chat, reseñas y administración existentes. Sin archivos ARB ni configuración l10n encontrados. |

Los servicios Go tienen health/readiness/métricas. Los módulos `internal/platform/security.go` de auth, user, match, chat, alert y admin repiten verificación OIDC: firma RS256, issuer, audience, expiración y roles del realm. Payment no tiene hoy endpoints de negocio protegidos. No hay módulo compartido `rac-platform` ni middleware de standing. El rol del JWT no basta para revocar un token antiguo; match además consulta el perfil local en su autorización.

## Identidad, publicación y medios

- `scripts/configure_identity.py` configura clientes públicos `rac-web` y `rac-mobile`, Authorization Code + PKCE S256; sin implicit ni password grant. Configura access token de 300 s. No se ha comprobado rotación efectiva, MFA obligatorio, brute-force protection ni verificación obligatoria de correo en el realm ejecutado.
- Roles `cliente`, `compa`, `admin`; compa compone cliente y admin compone ambos. No existen los roles separados T&S propuestos. No se reutilizará esa jerarquía para acceder a evidencia.
- `PUT /api/user/me/compa` publica sin aprobación previa y provisiona el rol compa mediante `rac-compa-provisioner`. Sus roles técnicos `manage-users` y `view-realm` son demasiado amplios para solo asignar compa.
- `usuario.verificado` refleja `email_verified` del JWT. No demuestra identidad ni mayoría de edad. No hay proveedor KYC, huella de documento ni control de menores.
- Habilidades libres; biografía, nombre y foto editables. No hay revisión inmutable ni snapshot público aprobado. Cambiar la foto o perfil actual podría cambiar el contenido público sin una revisión de publicación.
- Foto privada en RustFS, procesada a JPEG 512×512, límites de 5 MiB/12 MP y reencodificación que elimina metadatos. La API sirve la foto publicada; no hay cuarentena, OCR, pHash, legal hold ni ciclo de aprobación.
- Una reseña por reserva finalizada, 1–5 estrellas. No hay cola de moderación ni reporte específico de reseña. Debe reemplazarse la etiqueta ambigua de verificación por la procedencia de una reserva finalizada.

## Keycloak y RustFS: configuración versus garantía

Compose fija `quay.io/keycloak/keycloak:24.0`, sin digest: versión exacta ejecutada **no determinada**. La documentación de referencia 24.0.5 describe permisos administrativos finos como Technology Preview, desactivados por defecto, habilitables con `admin-fine-grained-authz`. No se encontró esa habilitación en la configuración examinada. Se requiere seleccionar una versión soportada, fijarla y probar permisos negativos antes de retirar el rol amplio; no extrapolar características de versiones nuevas a 24. [Guía oficial 24.0.5](https://www.keycloak.org/docs/24.0.5/server_admin/index.html).

`compose.storage.yaml` fija `rustfs/rustfs:1.0.3@sha256:9ca9559533b537d10482fe923288b676ad08f92a7069d9a17327fbae3cab688b`, con volúmenes de datos/logs y puertos locales 9000/9001. No configura un bucket de evidencia con COMPLIANCE. **Soporte efectivo COMPLIANCE: pendiente de prueba con ese digest.** El issue histórico #1509 afectaba alpha.79 y fue marcado corregido; no demuestra un defecto en 1.0.3 ni garantiza su funcionamiento. Un delete marker no equivale a eliminar una versión protegida: la prueba debe distinguir ambos. [Issue y resolución](https://github.com/rustfs/rustfs/issues/1509).

## Modelo persistente: V001–V017

Fuente: `db/migrations/`. No se modificará ninguna migración aplicada.

| Migración | Tablas / cambios relevantes |
|---|---|
| V001 | usuario, compa_perfil, skill, compa_perfil_skill, sesion, mensaje, pago, reporte, compa_availability; enums |
| V002–V003 | Integridad temporal de sesiones e índices de identidad Keycloak |
| V004 | sesion_cupo_semanal, compa_suscripcion |
| V005–V007 | notificacion; zona IANA; biografía/foto_clave |
| V008 | reserva_resena y validación de reserva finalizada |
| V009–V010 | Secuencia/idempotencia de mensaje, chat_cursor, chat_outbox |
| V011–V012 | chat_bloqueo, chat_reporte, chat_auditoria; límite de evidencia por versión de commit y límite legacy preservado |
| V013–V014 | booking_outbox, alert_event_inbox, alert_event_quarantine; índice de historial |
| V015–V017 | compa_time_off; enum expirada; vencimiento de pendientes y eventos v2 |

`usuario` conserva columnas históricas de nacimiento, teléfono, dirección y localización. No asumir que están vacías ni borrarlas sin inventario mínimo y revisión de retención. `reporte` de V001 convive con `chat_reporte`: su uso/datos deberá comprobarse al migrar. `chat_auditoria` no está encadenada y tiene relaciones con borrado en cascada: primero preservar historia y límites, luego retirar el modelo antiguo.

## Eventos, infraestructura y operaciones

- Reservas: `booking.state_changed`, schema_version 1 y 2 (expirada), outbox transaccional; relay hacia exchange topic `rac.bookings`; consumidor alert, cola quorum `rac.alert.bookings`. Fallos: exchange `rac.bookings.failed` y cola `rac.alert.bookings.failed`; inbox idempotente, cuarentena y ACK tras persistencia.
- Chat: `chat_outbox` y cursores para replay HTTP. No es hoy un consumidor RabbitMQ de standing ni un analizador de texto.
- No hay eventos de estado de cuenta, KYC, políticas, casos ni reconciliación de proyecciones. Añadir consumidores requiere ACL y colas explícitas, no compartir una cola entre servicios que necesitan recibir todos los cambios.
- Match conserva estados pendiente/activa/finalizada/cancelada/expirada, tres confirmaciones gratis por semana, vencimiento al inicio y mantenimiento periódico. El máximo actual de slot es 240 min, diferente de los 480 propuestos. Cancelación por enforcement y devolución de cupos deben definirse sin romper las reglas existentes.
- PostgreSQL separa la BD Keycloak y esquema `kc` con login propio, pero comparte cluster. Los servicios RAC usan la conexión de aplicación compartida; no hay aún separación completa de permisos DML por dueño.
- NGINX define rutas y algunos headers; la configuración local examinada no implementa CSP ni rate limiting integral. No prueba TLS productivo.
- Web usa `OidcWebStore` con cifrado requerido, no almacenamiento exclusivamente en memoria. Migrar tokens sin romper la transacción PKCE ni el redirect ya arreglado. Móvil usa almacenamiento seguro.
- Prometheus/Grafana/Loki y respaldos Restic locales existen. Copia cifrada programada: 7 diarias, 4 semanales, 3 mensuales. No hay copia independiente fuera del PC, tombstones ni procedimiento de restauración con supresiones/holds.

## Brechas que impiden habilitar usuarios reales

Standing transversal; revisión previa; KYC/edad; políticas aprobadas; acceso staff mínimo con MFA; auditoría resistente a alteración con anclaje; evidencia y privacidad; restauración que no reviva datos; procedimientos humanos de respuesta. El diseño no puede suplir un equipo responsable ni asesoría jurídica. Las pruebas de carga, permisos efectivos, restauración y COMPLIANCE siguen pendientes y deben bloquear los gates correspondientes.
