# P09 — preparación durable de promoción

V050 y user `5a28ead7887663ccc0b9d8672de1b39c90043c21`, preparación interna en
desarrollo. No hay ruta HTTP para este comando, flags activos, copia automática,
recibos/finalización o modificación del bloqueo de fotos de V045.

El operador debe registrar un destino privado (ID, hash de localizador de origen,
bucket y región) y una política inmutable que une política de publicación,
pipeline y destino. Cada política tiene un gate separado, falso por defecto.
Nada se siembra o habilita al migrar. Las configuraciones históricas no se
reescriben: al reemplazar una política hay que retirar su gate expresamente para
que una réplica con configuración antigua tampoco prepare nuevas promociones.

El intento durable fija evento humano, actor verificado, LOGIN, política de
revisión, revisión/hash/versión esperada, política de publicación, pipeline,
destino y resultado de procesamiento exacto. Su clave destino deriva del UUID
del intento, no de una URL/clave que envíe el cliente. Claves foráneas ligan la
foto al vínculo inmutable de la revisión y la configuración a la política.

Un evento repetido con los mismos parámetros conserva intento y clave destino.
Otro actor, LOGIN, política o comando no puede apropiárselo. Cada preparación,
incluido un retry válido, registra un intento de acceso nuevo, con vencimiento
de dos minutos y evento auditado. El dato de expiración es técnico; no establece
una retención jurídica. Preparación, acceso y cadena de auditoría se confirman
juntos. No se guardan tokens, texto OCR, imágenes o secretos S3 en esos registros.

La función verifica revisión pendiente/hash/versión, ausencia de decisión,
estado publicable, actor distinto del dueño, standing/restricciones, política
habilitada y fuente confirmada/procesada del pipeline autorizado. La política de
publicación debe estar autorizada por el registro, además de coincidir con el
snapshot. Una revisión antigua/configuración obsoleta no recibe metadatos para
copiar. Documentos, identidad, catálogo y demás condiciones deberán revalidarse
en la finalización, antes de publicar; preparar no los declara satisfechos.

El adaptador usa un LOGIN function-only con ready y prepare; no concede tablas.
La frontera compartida comprueba permisos staff/MFA y los grants reales antes y
después del SQL, confirma y libera locks antes de devolver metadatos privados.
La respuesta se compara con la configuración de destino elegida por el servidor.
Todavía no se conecta ese adaptador al aprobador: su integración debe conservar
esa separación entre transacciones e I/O y añadir el recibo/versionado exactos.

## Validación

- Compilación, race y vet de listingreview pasaron. Las pruebas SQL condicionadas
  no cuentan como ejecutadas en ese comando sin base de laboratorio.
- Ensayo preliminar de V050 + user af9b841:
  `.local/p09-promotion-intents-rustfs-2026-11-05.log`, relativo a la raíz RAC,
  exit 0. Se exigió PASS de
  `TestReaderPostgresHTTP/durable-photo-promotion-intent`: gate apagado, metadata
  exacta, intentos/reintentos/concurrencia, negativa de tablas, historial inmutable,
  fila de negocio desbloqueada al retornar, conflictos, estado obsoleto y rollback
  de MFA/auditoría. Usa Session staff sintética construida en el test, no un nuevo
  E2E de Keycloak. La suite conserva pruebas separadas de JWT/HTTP/preview y S3.
- Se añadió después el vínculo de política de publicación al registro y un caso
  que cambia snapshot y configuración de réplica sin autorización del registro.
  Su migración/user completa y el gate no superusuario están en ejecución:
  `.local/p09-promotion-intents-migrations-2026-11-05.log` y
  `.local/p09-promotion-intents-permissions-2026-11-05.log`. No se infiere éxito
  hasta comprobar ambos exit codes.

El ensayo no copia el intento a RustFS ni aprueba una foto. Falta coordinador,
recibo durable, finalización atómica con comprobaciones vigentes y rollback,
recuperación tras ACK perdido, lectura pública autorizada/retirada y restauración
de registros con datos. P08/P09 siguen abiertos.
