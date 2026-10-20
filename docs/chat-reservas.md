# Chat privado por reserva — primer incremento

Fecha: 2026-10-20.

`rac-chat-service` implementa una API de mensajes de texto vinculados a reservas y autenticados con OIDC. Su README documenta contrato y configuración.

## Reglas

Solo los dos participantes pueden acceder. Una reserva activa permite enviar; finalizada o cancelada conserva el historial en solo lectura. Una pendiente no habilita chat. El administrador no tiene permiso implícito para leer conversaciones ajenas. Los envíos usan UUID del cliente para reintentos sin duplicados. Todavía no hay adjuntos, sockets, push, edición, borrado ni confirmaciones de lectura.

## Migración V009

Reutiliza `public.mensaje`, existente en V001, sin copiar ni eliminar historial. Agrega `numero` (orden/cursor bigint), `envio_id` e índices. El límite de texto se aplica a nuevos envíos; `NOT VALID` evita rechazar la migración por mensajes históricos incompatibles con ese límite. El trigger verifica estado y remitente contra la reserva bloqueada con FOR SHARE, impidiendo que una cancelación se intercale entre validación y commit.

La tabla ya queda incluida en los respaldos de PostgreSQL; no se agrega un volumen ni bucket. La copia fuera del PC se deja para otra iteración.

## Entrega y validación

Se entregan PR de API y PR de esquema hacia `main`. Son dependientes: aplicar V009 antes de ejecutar el backend nuevo. El pipeline propio de chat prueba Go y PostgreSQL 16. El runner de migraciones de infra ejecuta también las pruebas contra las migraciones reales cuando encuentra el repositorio hermano actualizado. La integración alojada de infra aún clona los cuatro servicios actuales: esa segunda comprobación de chat es local en este incremento, no una garantía del CI general.

## Siguiente incremento

1. Listado paginado de conversaciones del usuario.
2. Incorporar chat a manifiestos de release, preflight, Compose y observabilidad, conservando promoción por imágenes inmutables y revisando acceso de CI al quinto repositorio.
3. Conectar Mensajes y accesos desde reservas en Flutter, con actualización, reintentos y estados vacíos/error/solo lectura en mobile y web.
4. Probar dos identidades reales por OIDC en navegador antes de habilitar el menú.

**Mensajes continúa en construcción** y el stack actual no levanta chat automáticamente. Este incremento entrega el backend probado, todavía no la función disponible en la app.
