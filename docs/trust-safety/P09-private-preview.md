# P09 — previsualización privada del JPEG revisado

Entrega de backend/proxy/consola, sin activar en DEV. No habilita aprobación,
promoción o lecturas públicas. ADR-011 sigue siendo el contrato del ciclo completo.
Fuentes y resultados: [expediente local](evidence/P09-private-preview-2026-11-05.md).

V049 agrega `listing_review.photo` al lector function-only. Resuelve únicamente
la referencia inmutable de una revisión que continúa pendiente y no tiene decisión;
no admite consultas por clave S3, dueño o fuente arbitraria. Devuelve metadatos
privados al proceso owner, nunca al cliente. Corrector, aprobador y cliente no
reciben esa función ni acceso directo a las tablas. La provisión explícita debe
actualizar el lector existente; V049 no concede permisos automáticamente.

La ruta privada `GET /internal/listings/revisions/{id}/photo` exige ListingsRead,
audiencia staff y MFA por la frontera existente. Sin inyección explícita de un
`PreviewStore` devuelve 503. No utiliza avatares como fallback. El puerto admite
solo lectura. La configuración runtime exige `RAC_ENV=dev`, opt-in explícito y
secretos montados de una identidad dedicada de staging; se probaron sus negativas
IAM contra RustFS real. No se concede lectura de cuarentena.

El owner hace dos resoluciones auditadas en transacciones cortas: una antes de
consultar almacenamiento y otra después. Cada una comprueba rol aislado y sesión,
y confirma su acceso en la cadena de auditoría antes de devolver el resultado.
Entre ambas lee el JPEG sin locks de negocio; comprueba SHA-256, tamaño y tipo de
contenido contra el recibo exacto del procesador. La segunda resolución debe
coincidir en revisión, versión del listing, digest del snapshot y del JPEG, clave
y tamaño. Si la revisión dejó de estar pendiente o la sesión expiró durante I/O,
no se entregan bytes. El punto de autorización es la última resolución confirmada;
no se promete revocar bytes que un navegador ya recibió.

Hay dos lecturas simultáneas como máximo por proceso; cada objeto está acotado a
5 MiB y el recorrido a 12 segundos. Las respuestas no se cachean; no se imprimen
claves, imágenes, texto OCR o errores privados de S3/SQL. Dos eventos en un acceso
exitoso representan las dos comprobaciones, no dos descargas humanas.

El laboratorio SQL/HTTP usa un LOGIN reader real, metadatos preparados sintéticos
y un almacén controlado: verifica contenido exacto y auditoría, rutas no públicas,
audiencia/rol negativos, ausencia de tienda, fuente no vinculada/superseded,
corrupción, error de lectura, expiración durante I/O, cambio de revisión, fallo de
la auditoría final y límite concurrente. El laboratorio de almacenamiento repite
ese recorrido con RustFS y la identidad real de solo lectura. El proxy admin se
prueba por separado con autenticación de ambos hops y respuestas acotadas; no se
presentan como un único E2E con navegador.

## Configuración opt-in

Antes de activar: aplicar migraciones, actualizar el LOGIN reader mediante la
provisión explícita, disponer del pipeline/buckets privados y comprobar IAM. La
herramienta DEV `configure_photo_pipeline.py` ahora requiere cuatro identidades
distintas: INGEST, READER (cuarentena), STAGING (worker) y PREVIEW (solo JPEG de
staging). Sus variables usan `PHOTO_<IDENTIDAD>_ACCESS_KEY/SECRET_KEY` en el proceso
operador; no se copian como texto al entorno de user-service.

El overlay `compose.photo-review.yaml` requiere endpoint/región, nombres separados
`RAC_PHOTO_QUARANTINE_BUCKET` y `RAC_PHOTO_STAGING_BUCKET`, y rutas de archivos
`PHOTO_PREVIEW_ACCESS_KEY_PATH` / `PHOTO_PREVIEW_SECRET_KEY_PATH`. Solo backend-user
recibe esos secretos, en `/run/secrets`. No publica el listener interno ni cambia
ACL del bucket. La ruta visible de la consola pasa por
`/api/admin/staff/listings/revisions/{id}/photo`, sin parámetros de destino.

`make ENV=dev STANDING_PREVIEW=1 LISTING_PREVIEW=1 PHOTO_REVIEW_PREVIEW=1 config`
verifica la configuración preparada; no activa ni provisiona recursos por sí mismo.
El flag nuevo vale 0 por defecto, exige LISTING_PREVIEW=1 y rechaza QA/PRD. Pasar el
overlay directamente fuera de Make tampoco evita el rechazo de entorno del owner.
En runtime se usan `RAC_PHOTO_PREVIEW_ACCESS_KEY_FILE` y
`RAC_PHOTO_PREVIEW_SECRET_KEY_FILE`, nunca fallback a variables de secretos planos.

La consola solicita los bytes solo al pulsar Ver foto, ligados a cuenta/revisión y
sin reintentos automáticos o refresh de MFA. Decodifica en una `ui.Image` propia y
usa `RawImage` con `BoxFit.contain`: no recorta ni añade las fotos a ImageCache o
preferences. Se descarta al ocultar la app, cerrar la vista, salir de staff o
recibir una respuesta de otra cuenta. Esto no impide capturas de pantalla de un
operador autorizado ni revoca una imagen ya entregada.

Pendiente: señales detalladas de imagen en el contexto de revisión, promoción
durable ligada al comando humano y su readback/versionado, navegación E2E con
OIDC real, corte público y retirada. Ver una foto no habilita el botón de aprobarla.
