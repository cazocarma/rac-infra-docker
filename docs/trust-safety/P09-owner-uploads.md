# P09 — preparación privada y estado para el propietario

Entrega local de V047 y su API/Flutter. La fuente privada puede subirse,
recuperarse y procesarse; todavía no se adjunta a una revisión de publicación,
aprueba ni promueve a medios públicos. No cambia `usuario.foto_clave` ni evita
el corte público pendiente de P08.

## Protocolo y autorización

| Ruta autenticada | Operación |
|---|---|
| `GET /api/user/me/photo-upload-config` | Disponibilidad configurada, tipos y límite de bytes. `enabled=false` produce pantalla «En construcción» |
| `POST /api/user/me/photo-sources` | Bytes JPG/PNG + `Idempotency-Key` UUID v4 canónico. Sin owner, claves, hash o pipeline elegidos por el cliente |
| `GET /api/user/me/photo-upload-requests/:id` | Recuperación por clave de petición, incluso si se perdió toda la respuesta original |
| `GET /api/user/me/photo-sources/:id` | Estado mínimo de una fuente propia |
| `POST /api/user/me/photo-sources/:id/confirm` | Cuerpo vacío; verifica los bytes privados y reintenta la confirmación atómica |

El principal verificado determina el propietario. Otro usuario recibe 404 para
su fuente; la misma clave de petición en otra cuenta es independiente. Las
lecturas propias siguen disponibles con suspensión/ban, sin conceder escritura.
Todas las respuestas de esta API tienen `Cache-Control: no-store`.

La reserva usa READ COMMITTED, lock NO KEY UPDATE sobre la identidad del dueño
y conteo separado después del lock. El máximo técnico de fuentes en las últimas
24 horas se comparte entre instancias; un reintento idéntico no consume otro
cupo. No es la regla comercial de tres reservas semanales ni un beneficio de plan.
Dos uploads simultáneos por instancia acotan buffers de hasta 5 MiB; el servidor
valida formato real, dimensiones y presupuesto antes de registrar la fuente.

Cada fase de escritura adquiere una autorización de standing nueva y acotada,
con su contexto SQL, y comprueba documentos/assessment aplicables y autoridad
justo antes del commit. No se mantiene un lock SQL durante Put/Get de objetos.
Una suspensión durante S3 impide confirmar/encolar; conserva la reserva privada
para recuperación y consulta, no crea una publicación.

V047 agrega `photo.upload_requests` append-only con FK compuesta fuente/dueño.
La clave de petición reutilizada con otros bytes, media o pipeline devuelve 409;
no reinterpreta silenciosamente fuentes antiguas al actualizar el pipeline.
`photo.owner_upload_status` es SECURITY DEFINER con search_path fijo y devuelve
solo ID/estado. `rac_user` no puede leer jobs, intentos ni evaluaciones crudas.

## Recuperación y privacidad

La reserva se confirma **antes** de escribir en cuarentena. Una escritura incierta
no se borra para compensar; el reintento conserva la clave del objeto y exige
readback SHA-256/tamaño. La confirmación y la intención de análisis son una
transacción idempotente. Un objeto existente alterado no se sobrescribe y no se
anuncia como recuperable por simple reintento.

Los estados son `awaiting_upload`, `queued`, `processing`,
`processing_unavailable`, `correction_required` y `awaiting_review`. No significan
aprobación, sanción de cuenta o publicación. No se devuelven keys, URLs, hashes,
scores, spans, reglas ni identidad de staff. La revisión humana pendiente sigue
marcada «En construcción» en la interfaz.

Flutter conserva únicamente un request ID por issuer/API/cuenta para recuperar
la operación. No persiste foto, token, URL ni resultado de moderación. La selección
no envía automáticamente: se muestra el encuadre completo y se pulsa «Enviar».
No se recorta/recomprime en el picker antes del OCR del servidor. El transporte
congela bytes/JSON y mantiene la misma clave durante un único refresh de token;
un cambio de cuenta impide reenviar bytes o revelar la respuesta de la anterior.

## Activación DEV explícita

Continúa desactivada por defecto. El servidor exige `RAC_ENV=dev` y
`RAC_PHOTO_UPLOADS_ENABLED=true`; fuera de DEV rechaza la configuración activa.
Requiere:

- `RAC_PHOTO_UPLOADS_PER_DAY` entre 1 y 100, elegido explícitamente.
- `RAC_PHOTO_PIPELINE_VERSION`, coherente con el worker y las políticas/releases
  técnicas del dueño SQL. Cambiarlo no migra fuentes anteriores.
- `RAC_PHOTO_S3_ENDPOINT`, `RAC_PHOTO_S3_REGION`, `RAC_PHOTO_QUARANTINE_BUCKET`.
- `RAC_PHOTO_INGEST_ACCESS_KEY_FILE` y `RAC_PHOTO_INGEST_SECRET_KEY_FILE`:
  identidad de ingesta Get/Put raw, distinta del avatar.

La credencial del worker usa los secretos `RAC_PHOTO_QUARANTINE_*_FILE` con la
identidad **lectora**, no la de ingesta. Staging conserva su identidad/bucket
separados. El servidor normal sigue usando su login dueño `rac_user`; nunca
copiar el secreto del migrador o root RustFS al servicio. El lector común de
secret files acota 8 KiB y elimina solo CR/LF finales, sin imprimir errores crudos.

No se aplicó V047 ni se habilitó el flujo sobre DEV en esta entrega. Las
dependencias jurídicas/retención antes de usuarios reales siguen pendientes.

## Evidencia local

- Ensayo preliminar del árbol de trabajo, consolidado después en user
  `bb80a0b523bdd065fa3fb66fc8dbddc2b8db6474`:
  `test_migrations.py --services user`, exit 0, registro
  `.local/p09-owner-api-migrations-2026-11-05.log`.
  Es un ensayo exploratorio, no un manifiesto congelado de revisiones.
  El candidato posterior `1dae264452c0de40b99a0a28edfe525128371354`
  agrega no-store también a denegaciones de autenticación y la prueba de header
  de idempotencia ambiguo. Su regresión congelada se registra por separado.
- `test_database_permissions.py`, exit 0: fresh/upgrade no superusuario,
  privacidad de tablas, FK del dueño, historial y dump/restore de peticiones/jobs;
  `.local/p09-owner-api-permissions-2026-11-05.log`.
- `test_photo_storage.py`, exit 0:
  `.local/p09-owner-api-rustfs-2026-11-05.log`. El HTTP usa el rol `rac_user`
  real con autenticación de principal inyectada de prueba; el worker usa un LOGIN
  function-only distinto. Bytes y OCR/S3/SQL son reales. No es un ensayo OIDC de
  navegador. Prueba ambos PNG sintéticos: contacto → corrección; benigno →
  revisión pendiente. Incluye además el contenedor real del worker.
- frontend `70d89dfc8ca478acbcdab46ffc432e6fb66b6802`, probado desde Git archive
  dentro del contenedor Flutter: formato, analyze sin observaciones, 268 pruebas
  y web release exit 0. Registro `.local/p09-frontend-70d89dfc8c.log`.
  Widgets en es/en, anchos 360/1200, recuperación y cambio de cuenta; no sustituye
  la matriz E2E final de navegador/móvil.
- Contratos OpenAPI: validación y 18 pruebas exit 0,
  `.local/p09-private-photo-contracts-final-2026-11-05.log`, commit
  `46078c8a89cab519afa7e2a0c2e3bdd208cc63d2` de rac-shared-contracts.

Sigue ligar una versión procesada a la revisión inmutable de P08, acceso privado
auditado de staff, decisión humana, promoción verificada y URLs autorizadas/
retirada. La promoción debe ocurrir al aprobar la revisión correspondiente;
una foto preparada por sí sola no debe aparecer públicamente.
