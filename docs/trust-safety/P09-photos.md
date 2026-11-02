# P09 — Fuentes privadas de fotos

Estado: base local en desarrollo, sin endpoint ni worker conectado. No cambia
el avatar actual, no certifica fotos legacy ni habilita obligatoriedad de rostro.
P08/P09 continúan abiertos; una fuente confirmada no es una foto aprobada.

## Flujo preparado

`photoassets.Prepare` inspecciona magic bytes y dimensiones mediante el mismo
validador que `photos.Normalize`, limita tamaño y congela bytes, SHA-256, tipo
declarado, dimensiones y versión explícita del pipeline. Genera un ID aleatorio
y una clave opaca `.raw`, sin nombre de usuario ni nombre del archivo original.
Inspeccionar la cabecera no equivale a decodificar, limpiar EXIF ni analizar la
imagen; eso sigue siendo trabajo del procesador.

El servidor debe confirmar `Reserve` en PostgreSQL antes de escribir el objeto
privado. Así una respuesta incierta de S3 conserva una referencia recuperable.
`Load` recupera sus metadatos únicamente para el subject dueño. `Verify` lee los
bytes reales desde el adaptador privado, fuera de bloqueos de BD, y compara
longitud y SHA-256; conocer un hash o un ETag no confirma una subida.

`Confirm` revalida pertenencia e identidad del descriptor y, dentro de la
transacción del llamador, inserta confirmación y una intención de análisis. El
llamador hace commit o rollback completo. Reintentar o confirmar desde dos
instancias no crea trabajos duplicados. No escribe `usuario.foto_clave`, una
revisión de publicación ni una aprobación. No hay consumidor de esta outbox aún.

V044 crea `photo.sources`, `photo.upload_confirmations` y
`photo.analysis_outbox`. Un FK compuesto exige que hash/tamaño confirmados
coincidan con los reservados. El historial rechaza UPDATE/DELETE ordinarios,
también del propietario de migraciones. No se guardan bytes originales ni OCR
en PostgreSQL. La saga de supresión/holds de P12 es requisito antes de activar
con datos reales; una constraint no constituye una política jurídica de retención.

## Almacenamiento

El contrato `photostore.Put` ahora es crear sin sustituir. Local conserva O_EXCL;
S3 usa `If-None-Match: *` atómico y distingue objeto existente de conflicto de
creación. Hacer HEAD antes de PUT dejaría una carrera. Esto protege la operación
de la aplicación: no es WORM ni impide que una credencial privilegiada borre y
recree el objeto.

`NewQuarantineS3` admite solo claves opacas `.raw`, usa
`application/octet-stream` y expone crear/leer/comprobar, sin Delete, URL pública
o presign. El almacenamiento JPEG actual conserva su contrato `.jpg`. La
cuarentena necesita bucket e identidad IAM separados antes de activarse; la
ausencia de Delete en una interfaz Go no sustituye permisos del servidor S3.

## Laboratorio y evidencia inicial

`scripts/test_photo_storage.py` ya no lee `.env.storage`, no utiliza la red DEV
ni publica puertos. Crea RustFS fijado por digest, PostgreSQL, red, tmpfs e
identidades sintéticas y retira esos recursos. Usa bases distintas para la API,
el registro de fuentes y la migración: los paquetes Go se ejecutan en paralelo y
el migrador recorre todas las referencias de su BD.

Exige los PASS reales de creación condicional concurrente, registro/confirmación
con S3, API de fotos y copia con integridad/reintento; no acepta un skip como
prueba. Reutiliza el ensayo IAM del bucket de perfiles: no afirma que el IAM de
la futura cuarentena o `public-media` ya esté provisionado. El primer ensayo
terminó exit 0 (`.local/p09-hermetic-photo-storage.log`), al igual que vet y race
de user-service (`.local/p09-user-unit.log`).

Se repitieron permisos/restauración, migraciones/user y almacenamiento desde
Git archives de infra `825f521`, user `264551c`, platform `42dbb345` (v0.16.0)
y los otros seis repos fijados. Los tres comandos terminaron exit 0 en
`.local/rac-p09-source-proof-d778fa1cd93e/`:
`revisions.json`, `permissions.log`, `migrations-user.log`, `photo-storage.log`.
La restauración conservó fuente, digest/tamaño, confirmación e intención de
análisis. El ensayo Go sin S3 exigió el PASS de la variante PostgreSQL/memoria;
el laboratorio S3 exigió explícitamente la variante PostgreSQL/RustFS y las
pruebas de la API y migración. No se aplicó V044 a DEV y no hubo push ni cambio
de los pins activos de CI. Los recursos desechables fueron retirados.

## Trabajo restante de P09

- API de subida/reanudación, autorización y estado, límites/observabilidad y
  reconciliación de operaciones inciertas; configuración de cuarentena separada.
- Worker con claims/reintentos/fencing, decodificación y reencode sin EXIF,
  pHash/OCR locales, señales compartidas y artefactos inmutables versionados.
- Corpus de transformaciones y falsos positivos; una coincidencia es señal,
  nunca prueba de identidad ni sanción automática. Moderación externa sigue off.
- Revisión humana, promoción verificada a `public-media` privado y referencias
  de revisiones a la versión aprobada. Cambiar/eliminar el avatar no sustituye un
  objeto aprobado; retirar un medio debe invalidar sus publicaciones.
- Lecturas y URLs firmadas breves con autorización central; IAM negativo de
  cada bucket/operación, backups y supresión/holds coordinados con P10/P12.
- Corte de rutas legacy y pruebas de teléfono en foto, EXIF, recorte/recompresión,
  navegación directa, recursos retirados y ACL reales, junto con P08.
