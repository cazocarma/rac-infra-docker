# P09 — previsualización privada del JPEG revisado

Entrega de backend en desarrollo, sin activar en DEV. No habilita aprobación,
promoción o lecturas públicas. ADR-011 sigue siendo el contrato del ciclo completo.
Fuente user: `c11c345e851b6d371deedf742223a28cdaf80b96`. Las pruebas SQL completas
están en ejecución; no se da por pasada su aceptación por haber compilado el paquete.

V049 agrega `listing_review.photo` al lector function-only. Resuelve únicamente
la referencia inmutable de una revisión que continúa pendiente y no tiene decisión;
no admite consultas por clave S3, dueño o fuente arbitraria. Devuelve metadatos
privados al proceso owner, nunca al cliente. Corrector, aprobador y cliente no
reciben esa función ni acceso directo a las tablas. La provisión explícita debe
actualizar el lector existente; V049 no concede permisos automáticamente.

La ruta privada `GET /internal/listings/revisions/{id}/photo` exige ListingsRead,
audiencia staff y MFA por la frontera existente. Sin inyección explícita de un
`PreviewStore` devuelve 503. No utiliza avatares como fallback. El puerto admite
solo lectura; falta aún conectar la configuración runtime y probar una identidad
IAM dedicada que solo pueda leer staging, antes de habilitarlo en el stack.

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
la auditoría final y límite concurrente. No equivale a probar RustFS con la nueva
identidad, proxy admin o navegador. Esos recorridos y la promoción siguen pendientes.
