# Bandeja privada de notificaciones

`rac-alert-service` implementa la API de la bandeja que antes estaba en usuarios. HTTP adapta OIDC/errores; `internal/inbox` valida las operaciones mediante una interfaz de repositorio; `internal/repo` implementa PostgreSQL. El frontend comparte transporte autenticado con chat, con timeout y un único intento de renovación de sesión.

## API y permisos

- GET `/api/alert/notifications?limit=20&offset=0`: lista propia por fecha/id descendentes, `items`, `has_more` y `no_leidas` global. Límite 1–100 y offset 0–10000; colección vacía como array. Una transacción de solo lectura con snapshot repetible mantiene contador y página coherentes.
- PUT `/api/alert/notifications/:id/read`: marca propia; los reintentos conservan la primera hora. UUID ajeno o inexistente devuelve 404 también para administradores; formato inválido devuelve 400.
- PUT `/api/alert/notifications/read-all`: marca solo avisos propios pendientes visibles en el snapshot de la sentencia. Devuelve `actualizadas`; un reintento sin avisos nuevos devuelve cero. Los avisos que lleguen después permanecen pendientes.

Los tres endpoints requieren Bearer OIDC con audiencia rac-api y rol cliente/compa/admin. La identidad siempre sale de `sub`, nunca de un parámetro usuario_id. Las respuestas privadas usan `Cache-Control: no-store`. Errores de dependencia devuelven 503 sin filtrar mensajes de SQL ni credenciales.

Las antiguas rutas `/api/user/notifications` y `/api/user/notifications/:id/read` son alias del gateway hacia la misma API de alertas. User-service ya no tiene handlers ni SQL de notificaciones. Se conserva compatibilidad sin duplicar la implementación ni crear una llamada HTTP de user-service a alert-service.

## Persistencia y despliegue

No se reescriben migraciones aplicadas ni se borra/backfillea la bandeja. V013 sustituye el productor V005 por outbox transaccional de reservas. El consumidor de alertas guarda inbox y notificaciones antes del ACK. La BD continúa compartida; ver [mensajería](mensajeria-rabbitmq.md) para garantías y operación.

Compose agrega backend-alert, checks de readiness sobre las columnas usadas, métricas internas Prometheus y logs estructurados sin contenido de avisos. No se expone puerto del backend al host. QA/PRD requieren `ALERT_IMAGE` por digest junto a las otras cinco imágenes. Los manifiestos anteriores sin alertas son rechazados por preflight, en lugar de desplegar una versión incompleta.

El CI integrado descarga seis repositorios por SHA; requiere sumar únicamente rac-alert-service a la instalación de la App de lectura. No se incorpora un PAT ni se amplían permisos de escritura. Su CI propio prueba PostgreSQL 16 desechable; no ejecuta DDL de pruebas sobre DEV. El contenedor de prueba local y la base rac_alert_test son independientes de los datos del usuario.

## Validación

Go: JWT real firmado, rol/anonimato, paginación inválida, identidad ignorada en query, error 503 sin filtrado, aislamiento por propietario, timestamp idempotente, marcado concurrente, contador global y aviso posterior. Usuarios mantiene sus pruebas sin handlers duplicados. Flutter verifica renovación con el mismo PUT, error sin ocultar pendientes y marcado confirmado. El navegador usa un comprador OIDC desechable, comprueba alias antiguo, contador, reintento masivo y cancelación posterior que genera un aviso nuevo; limpia únicamente su fixture.

Correo/push siguen pendientes. El [flujo RabbitMQ](mensajeria-rabbitmq.md) implementa outbox y consumo idempotente.
