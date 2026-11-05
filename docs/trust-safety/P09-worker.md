# Worker privado de fotos

Entrega local de P09. No aprueba fotos, publica objetos ni decide sanciones.
El ejecutable `cmd/photo-worker` está restringido a `RAC_ENV=dev`; no se agregó
a Compose ni se aplicó V046 a DEV durante su desarrollo.

## Cola y transacciones

V046 materializa cada intención de `photo.analysis_outbox` como un job en la
misma transacción, incluyendo backfill de intenciones anteriores. Un claim
actualiza el job bajo `FOR UPDATE SKIP LOCKED`, inserta un intento inmutable y
devuelve su descriptor privado. El intento queda confirmado antes de leer S3
o ejecutar OCR. Cada intento recibe un UUID nuevo y una clave JPEG diferente;
los archivos de intentos inciertos quedan referenciados y requieren reconciliación,
no borrado compensatorio inmediato.

Solo se reclaman pipelines con política técnica y release registrados por el
dueño de la base. No hay semillas ni configuración activa en la migración.
La política limita lease, backoff y número de intentos; al agotarlos el job
permanece sin completar para investigación, sin un bucle ilimitado. Cambiar el
release no reinicia el contador. Los intentos conservan commit y digest; estos
datos declarados por el operador no son una atestación del proceso en ejecución.

El resultado referencia exactamente intento y fuente. La finalización compara
lease vigente con reloj PostgreSQL, intento activo, release, clave, digest y
campos esenciales de la evaluación. Un trigger diferido vuelve a comprobar el
vencimiento al confirmar la transacción. Resultado y finalización del job son
atómicos; un reintento idéntico tras perder el ACK devuelve éxito, aunque ya
haya vencido el lease. Un recibo distinto del mismo intento es conflicto; otro
intento anterior no puede finalizar el trabajo. Intentos y resultados son
append-only. Esto no es el EvidenceStore/WORM de P10.

## Permisos y configuración

`NewPostgresQueue` exige un LOGIN aislado usando el verificador compartido y
repite la comprobación antes de cada operación. Solo requiere USAGE de `photo`
y EXECUTE de:

- `photo.claim_processing(text,text,text)`
- `photo.complete_processing(uuid,uuid,text,text,text,text,bytea,integer,jsonb,text,integer)`

No necesita permisos directos sobre ninguna tabla, membresías de roles de
servicio, CREATE, superusuario ni BYPASSRLS. La migración no crea ni otorga
permisos a un login del worker. Configurar el usuario de migraciones como
credencial de ejecución es rechazado. Configuración de políticas/releases y
reconciliación quedan fuera de su autoridad.

El ejecutable requiere estos archivos de secretos montados solo para lectura:

- `RAC_PHOTO_QUEUE_DATABASE_URL_FILE`
- `RAC_PHOTO_QUARANTINE_ACCESS_KEY_FILE` y `RAC_PHOTO_QUARANTINE_SECRET_KEY_FILE`
- `RAC_PHOTO_STAGING_ACCESS_KEY_FILE` y `RAC_PHOTO_STAGING_SECRET_KEY_FILE`

También requiere `RAC_ENV=dev`, `RAC_PHOTO_S3_ENDPOINT`, `RAC_PHOTO_S3_REGION`,
`RAC_PHOTO_QUARANTINE_BUCKET`, `RAC_PHOTO_STAGING_BUCKET`,
`RAC_PHOTO_PIPELINE_VERSION`, `RAC_PHOTO_BUILD_COMMIT` y
`RAC_PHOTO_IMAGE_DIGEST`. La imagen configura rutas absolutas de OCR mediante
`RAC_PHOTO_OCR_BINARY` y `RAC_PHOTO_OCR_DATA_DIR`. No contiene credenciales ni
publica puertos. El runtime corre como UID/GID 10001.

Quarantine y staging deben tener buckets y access keys distintos. Eso evita
una configuración accidentalmente compartida; por sí solo **no demuestra IAM**.
`configure_photo_pipeline.py` exige DEV explícito y aprovisiona tres identidades:
ingesta Get/Put `.raw`, lector Get `.raw`, staging Get/Put `.jpg`. No concede
listado, borrado, ACL ni administración. El laboratorio de almacenamiento debe
comprobar sus permisos positivos y negativos contra RustFS real. No reutilizar la cuenta administrativa RustFS ni
el bucket de avatares. Antes de ejecutar usar filesystem raíz de solo lectura,
tmpfs acotado, límites CPU/memoria/pids, sin privilegios y conectividad mínima.

El diccionario inicial se usa solo como señal privada en DEV. Sin catálogo
caso/evidencia para similitud, esa comprobación sigue `not_configured`; nunca
se interpreta como aprobación. Los logs contienen estados fijos, sin errores
crudos de drivers, claves, IDs, evaluación ni texto OCR.

## Validación requerida

`test_migrations.py --services user` exige `TestPhotoQueuePostgres` sobre una
base desechable `photo_processing` y un LOGIN real con las dos funciones. Cubre
claim concurrente, permisos negativos/drift, release distinto, rollback de
resultado, replay exacto/conflictivo, expiración, intento obsoleto, agotamiento
y vencimiento al COMMIT. La prueba del coordinador con intercalado simulado
se conserva, pero ya no sustituye la prueba de persistencia.

Pendientes de P09: despliegue controlado y operación de IAM/cola/proceso, subida y
estado para el propietario, reconciliación operativa/observabilidad, revisión
humana, promoción, URLs autorizadas, retirada y corte público de P08. No se
debe activar con datos reales antes de las dependencias de privacidad/retención.

## Evidencia local de runtime — 2026-11-05

El expediente de revisiones, comandos, permisos, regresión congelada y límites
de esta entrega está en [evidence/P09-worker-2026-11-05.md](evidence/P09-worker-2026-11-05.md).

`test_photo_storage.py` ahora ejecuta también
`photo_worker_runtime_fixture.py`: construye `Dockerfile.photo-worker`, registra
el commit de user y descriptor OCI exactos, siembra una fuente sintética y arranca
el ejecutable real con el LOGIN aislado. Usa tres identidades IAM distintas,
secretos por archivos, UID/GID 10001, raíz de solo lectura, tmpfs acotado,
capabilities vacías, no-new-privileges y límites de CPU/memoria/pids. Requiere que
OCR nativo genere `contact_correction_required` con revisión humana pendiente;
los logs solo admiten los dos mensajes fijos esperados. No promueve objetos.

El ensayo local terminó exit 0 con user `dfb83d2127acc1f2db29b7983fc6e209bd6ec62d`
y descriptor de worker
`sha256:015a3fddbac4edb3df06b308cbea0463b15ca8b2d3b7c1ba57d8fdc9425c75b0`.
Registro: `.local/p09-worker-daemon-2026-11-05.log`. Las fuentes son sintéticas;
la reserva/confirmación del ledger se siembra como fixture, no prueba una API
de subida del propietario. El laboratorio crea redes/bases/buckets desechables,
sin leer `.env`, usar redes DEV o publicar puertos. V046 no se aplicó a DEV.
