# P09 — destino versionado de medios: adaptador en desarrollo

User `c983f89e46c992573e218140e0d4cca5ee253315` agrega `VersionedS3`; el test de
proveedor está en `ca80ccc92d600a7f3788767b523f056b296be293`. Está separado del
almacén de avatares, del origen de cuarentena y de evidencias legales. No se
configura o activa en el stack. No equivale a promoción ni aprobación.

La creación usa If-None-Match y captura VersionId del proveedor. Empty/null
falla: un PUT exitoso sin versión no sirve como recibo. Si el ACK se pierde se
conserva el intento durable (aún pendiente de integrar); Current permite recuperar
la versión leída, pero nunca constituye una referencia pública por latest.
Version exige un identificador explícito y rechaza una respuesta de otra versión.
Se acotan lecturas a 5 MiB. No se usa ETag como hash, ni se expone Delete, ACL,
List o URL pública. El coordinador deberá verificar los bytes contra el digest
esperado antes de emitir el recibo.

El transporte S3 existente comparte ahora sus helpers de creación/lectura con el
adaptador, manteniendo el contrato de avatares sin requerir versiones para ellos.
Se probaron localmente race y vet de photostore: cabeceras condicionales, versión
opaca con caracteres que deben codificarse, idempotencia sin sobrescribir, lectura
por versión exacta, ausencia de versión, versión distinta, copia de bytes y tamaño.
Una expectativa del test que confundía el parámetro interno x-id del SDK con una
versión solicitada se corrigió para comprobar únicamente versionId.

## Proveedor e IAM comprobados

`python scripts/test_photo_storage.py` terminó exit 0, registro relativo a la raíz
RAC `.local/p09-versioned-media-rustfs-2026-11-05.log`. El user estaba limpio en
ca80ccc; las herramientas de infra son el árbol consolidado en esta entrega.
Se exige PASS de `TestVersionedMediaS3Integration`, sin aceptar un skip. RustFS
1.0.3 recibe PUT condicional mediante el SDK Go, devuelve un VersionId no nulo y
permite leer exactamente esa versión; el retry encuentra el mismo objeto y una
versión inexistente no cae a latest. Los escenarios previos de avatares, fuentes,
cola, upload HTTP, OCR nativo y preview privado también pasaron tras compartir
los helpers S3.

`configure_photo_media.py` es una provisión explícita DEV: exige media, staging,
cuarentena y perfiles en cuatro buckets separados, y una quinta identidad
PROMOTER distinta de root, perfiles e identidades de pipeline. No sustituye
políticas de bucket existentes: las rechaza. Habilita versionado del destino y
no configura retención/WORM ni flags de aplicación.

El permiso permite Get de JPEG en staging y Put/Get/GetObjectVersion de JPEG en
media privado. El laboratorio comprueba que una escritura posterior del operador
no cambia la lectura por VersionId anterior. Deniega originales, otros sufijos,
escritura en staging, Delete (incluida versión), List, ACL, política y configuración
de versionado; la lectura anónima falla. El operador conserva sus facultades:
esto no es evidencia legal inalterable o protección contra borrado privilegiado.

La imagen del worker probada en esa ejecución fue
`sha256:3618ea015f1a614f09d0b0eb79e4c707ed376521f769648f3a5dcd354b5ada34`.
Se retiraron los contenedores/red/tmpfs de laboratorio, sin tocar DEV ni leer .env.

Pendiente: intentos/recibos SQL y coordinador de copia/readback, contexto de señales,
revalidación/finalización de la aprobación y reconciliación, resolución autorizada
por VersionId/retirada y respaldo/restauración de estos buckets y referencias.
Las pruebas del proveedor no autorizan a abrir el gate de fotos de V045.
