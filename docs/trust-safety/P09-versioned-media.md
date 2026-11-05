# P09 — destino versionado de medios: adaptador en desarrollo

User `c983f89e46c992573e218140e0d4cca5ee253315` agrega `VersionedS3`, separado del
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

Pendiente de esta pieza: laboratorio RustFS versionado y su identidad IAM mínima,
intentos/recibos SQL y coordinador de copia/readback, revalidación/finalización de
la aprobación y reconciliación. Las pruebas HTTP de protocolo no sustituyen la
prueba del proveedor ni autorizan a abrir el gate de fotos de V045.
