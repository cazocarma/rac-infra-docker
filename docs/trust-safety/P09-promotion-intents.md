# P09 — preparación durable de promoción

V050 y user `2488ecbd0a1622c93be6365799d1438f2e752b1e`, preparación y copia
interna. No hay ruta HTTP para este comando, flags activos, finalización/recibos
durables o modificación del bloqueo de fotos de V045.

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
  Su migración/user completa y el gate no superusuario terminaron exit 0:
  `.local/p09-promotion-intents-migrations-2026-11-05.log` y
  `.local/p09-promotion-intents-permissions-2026-11-05.log`, con user 5a28ead y V050
  del árbol consolidado en infra ad8f79c. La copia posterior se prueba aparte.

## Copia verificada posterior a la preparación

`copyPreparedPhoto` no acepta un handle SQL o transacción. Requiere el marcador
privado que prepare emite después del commit y la validación de metadatos; al
serializar/deserializar el intento se pierde ese marcador y no puede copiarse sin
prepararlo nuevamente. Es una protección de uso del código, no una firma contra un
proceso comprometido. La función verifica sesión/actor y expiración, lee staging,
comprueba digest/tamaño/JPEG, crea condicionalmente y lee siempre VersionId exacto.

Si el destino ya existe, obtiene su versión y verifica sus bytes; no asume que
exists equivale a correcto. Un ACK perdido conserva el objeto y permite otro
intento auditado sobre la misma clave. Permisos y expiración se comprueban entre
operaciones y después del readback. El contexto está acotado a 20 segundos. Los
puertos carecen de Delete/ACL/URL pública; un error no borra compensatoriamente.
El recibo que devuelve solo existe en memoria y no es todavía una decisión.

Pruebas unitarias race y vet: `.local/p09-promotion-copy-unit-2026-11-05.log` y
la ejecución posterior del paquete, exit 0. Cubren ACK perdido tras persistir,
recovery de versión exacta, readback obligatorio incluso tras PUT exitoso,
corrupción/truncamiento/error, versión nula, metadatos sin commit, roundtrip JSON,
actor/permisos, expiración durante I/O y cancelación. Los tests DB condicionados
del comando de unidad no sustituyen sus laboratorios.

El laboratorio posterior exige
`TestReaderPostgresHTTP/durable-photo-promotion-intent/rustfs-copy-readback`:
intento SQL confirmado → lectura del JPEG saneado en staging → creación privada
versionada → readback exacto → segundo intento preparado que recupera la misma
versión. Registro `.local/p09-promotion-copy-rustfs-2026-11-05.log`, exit 0, con
user 2488ecb limpio y herramientas del árbol consolidado en esta entrega. La
imagen del worker fue
`sha256:4b8d5fa137a306583a20d6defad9a333e482ca90290e6d89f4cad55fdc865782`.
La prueba termina sin publicación, luego retira sus contenedores/red/tmpfs.

Falta integrar al aprobador el recibo durable y la finalización atómica con
decisión/auditoría/outbox/referencia/puntero, revalidar documentos/identidad,
standing, catálogo, políticas y MFA vigentes, y recuperar una finalización con
ACK perdido sin copiar otra vez. Debe comprobarse también el vencimiento al
COMMIT con reloj DB (deadline derivado de la sesión verificada, no del cliente),
no solo antes de invocar commit. Luego siguen URLs autorizadas/retirada y restore
de registros con datos. P08/P09 siguen abiertos.
