# P09 — endpoint de aprobación de foto: opt-in DEV

User `40071d8b66ed8316ba957b360eb1f20741d56e16`, admin
`5b1d2dfb963df039a0b1a797eaa89daaf73bea14`, V052. No se ejecutó provisión o
activación sobre DEV, ni push/CI remoto. La consola aún no invoca este comando.

## Endpoints y autoridad

El proxy admin agrega POST
`/api/admin/staff/listings/revisions/{id}/photo-approval`, que solo reenvía al
endpoint privado fijo del owner. El cuerpo es el comando congelado de P08:
event_id, expected_version como texto y sha256 de la revisión. No admite actor,
URL, bucket, estado aprobado, versión S3 o requisitos elegidos por el cliente.
Ambos servicios verifican audiencia, rol y MFA staff. El customer router no
registra la ruta. Dos operaciones simultáneas por proceso como máximo.

GET `/api/admin/staff/listings/capabilities` devuelve solo
`photo_approval_enabled: boolean`, con autorización ListingsRead y no-store.
Es falso si no hay aprobador configurado o su política/destino dejó de estar
habilitado. No expone claves, pipeline, endpoints o identidades. V052 verifica la
tupla completa de política de revisión/publicación, pipeline, destino y hash de
localizador/bucket/región; el constructor y readiness fallan ante discrepancias.

El cuarto LOGIN opcional `rac_listing_photo_approver` tiene seis funciones: las
cinco de V051 más photo_promotion_ready. No obtiene aprobación ordinaria,
approve_core, lectura de previews o tablas/columnas. Los tres logins existentes
conservan su configuración si el flag está apagado. La herramienta de provisión
solo incluye el cuarto con `RAC_PHOTO_PROMOTION_ENABLED=true`, exige un secreto
distinto y rechaza autoridad excesiva incluso en una segunda ejecución.

La configuración runtime exige RAC_ENV=dev y preview habilitado. El aprobador usa
una credencial PROMOTER distinta, montada en archivos, capaz de leer JPEG de
staging y crear/leer versiones en media privado. Bucket media, staging y
cuarentena deben ser distintos y no pueden coincidir con perfiles S3. El destino
se compara con el registro antes de servir; no se crea o habilita automáticamente.

Los plazos son compatibles con el flujo: owner limita la operación a 35 s, la
copia a 20 s y cada transacción a 3 s; el proxy de esta operación tiene deadline
38 s/cliente 40 s y los servidores WriteTimeout 45 s. Las demás operaciones
conservan sus límites de transporte. No hay reintentos automáticos del proxy.
Un vencimiento detectado por el fence SQL se comunica como step-up requerido.

## Preparar configuración

`PHOTO_PROMOTION_PREVIEW=1` exige ENV=dev, STANDING_PREVIEW=1, LISTING_PREVIEW=1 y
PHOTO_REVIEW_PREVIEW=1. Agrega compose.photo-promotion.yaml después de las capas
existentes. Requiere DSN del nuevo LOGIN, pipeline/target registrados y bucket
versionado, además de PHOTO_PROMOTER_ACCESS_KEY_PATH/SECRET_KEY_PATH. Los archivos
solo se montan en backend-user; database-config recibe únicamente su DSN/flag.
No publica puertos internos ni crea cuentas staff.

`make ... listing-review-db-config` provisiona las capacidades según los overlays
elegidos. Antes de arrancar hay que registrar explícitamente los datos de destino,
política y gate DEV de V050; no son una aprobación jurídica de D04–D14. La
herramienta general para ese registro y su receta operativa siguen pendientes.
La promoción permanece apagada por defecto y QA/PRD rechazan estos flags.

## Pruebas locales

Registros relativos a raíz RAC:

- `.local/p09-photo-http-unit-2026-11-05.log`: race/vet listingreview, exit 0.
- `.local/p09-photo-approval-proxy-2026-11-05.log`: race/vet proxy/http/server
  admin, exit 0. Rutas/cuerpo congelados, ambas audiencias, permisos, sanitización,
  validación estricta del booleano, decisión correcta y rechazo de destino ajeno.
- `.local/p09-photo-ingress-rustfs-2026-11-05.log`: exit 0, user 40071d8 limpio;
  exige `photo-finalization/staff-http`, con JWT firmado verificado mediante
  JWKS de prueba, actor falso/cuerpo inválido y replay HTTP sin I/O/duplicados.
  También comprueba capabilities false/true/retirado y rechazo de configuración
  física distinta. No equivale a navegador con Keycloak real ni a un único E2E
  admin→owner→RustFS. Imagen del worker:
  `sha256:a7aed3edb4f3c42a1e938a69518eaa1a27d52b81941f8d40e940a5cea0bf690a`.
- `.local/p09-photo-ingress-permissions-2026-11-05.log`: exit 0, fresh/upgrade no
  superusuario, opt-in/idempotencia del cuarto LOGIN, seis funciones, negativa de
  datos/otras funciones y rechazo de un grant extra de columna.
- Render Compose y gates Make: 2 tests exit 0; provisión/configuración: 4 tests
  exit 0; parser de 111 fuentes Python exit 0.
- `.local/p09-photo-ingress-migrations-2026-11-05.log`: exit 0, fresh/upgrade,
  repetición/checksums y regresión user/P08, con el nuevo staff HTTP exigido.

## Recuperación del comando Flutter

El frontend incorpora comandos cerrados para aprobación de publicaciones, con
evento, revisión, hash y versión decimal de PostgreSQL sin conversión a double.
El intento durable guarda el comando antes del envío y exige un recibo con el
mismo evento/revisión, decisión aprobada y versión siguiente antes de borrarlo.
Un `staff_step_up_required` recibido después de un POST conserva el resultado
como incierto: el proxy puede haberlo emitido después del commit del owner.
Un cambio de cuenta antes del envío impide despachar; después del envío conserva
la recuperación para la identidad original. El journal admite un namespace
separado del editorial y mantiene el aislamiento por issuer, subject y origen.

ListingReviewConsole usa el journal antes de cada envío. Al recargar, recupera
los comandos de la cuenta y ofrece un reintento explícito aunque la revisión ya
no esté en la cola; nunca reenvía durante la carga. Un fallo de almacenamiento o
recuperación bloquea nuevas escrituras. StaffScreen comparte el store seguro,
pero separa el namespace de documentos y publicaciones. Los rechazos definitivos
del primer intento permiten una decisión nueva; tras un resultado incierto solo
un recibo exacto permite resolver el evento. El doble clic no inicia otro envío.
La aprobación de fotos sigue cerrada hasta completar las señales y confirmación.
Las pruebas focalizadas cubren reinicio con MFA, aislamiento, recibo exacto y
versiones mayores al entero seguro de JavaScript. La prueba no usa Keycloak real.

Validación local del frontend `bf8a92f9413dbbbc928df130d95370382e7e8853`,
exportado desde Git limpio a Linux con Flutter 3.44.0:
`.local/p09-frontend-bf8a92f941.log`, exit 0. Formato, análisis sin avisos,
281 pruebas y build web release completados. La primera ejecución
`.local/p09-frontend-eab6634898.log` terminó con exit 1 por cinco avisos de
llaves en el análisis estático; se conserva como fallo, corregido en el commit
validado. La conexión del journal a la consola se validó igual en
`4910d783b7c35f7941257a66c70132b4487edaef`:
`.local/p09-frontend-4910d783b7.log`, exit 0, 282 pruebas y build web release.
Los manifiestos fijan ese SHA.

Pendiente de UI: usar capabilities para habilitar la acción, mostrar las señales
de la foto y su vista exacta, confirmación humana explícita y vínculo del comando
a la cuenta staff. Renovar MFA puede ocurrir después de que el owner ya haya
confirmado; esa respuesta debe tratarse como incierta y conservar el evento para
consultar/reintentar con la misma identidad, sin recopiado automático ni nuevo ID.
También faltan la integración real de todos los hops/navegador, corte público,
URLs/retirada y restore con datos. No se declara P08/P09 cerrado.
