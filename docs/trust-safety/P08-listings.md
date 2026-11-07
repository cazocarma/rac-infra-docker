# P08 — Revisiones de publicaciones

Estado: base local en desarrollo sobre P07. La CI del PR P07 #12 terminó completa
en SUCCESS (run 41467621049). P08 no está publicado ni conectado al stack o a
pantallas; los ingresses privados están en ensayo local. La publicación anterior
de la app no se considera una revisión humana.
No se activa la migración en DEV por inferencia de los ensayos desechables.

## Modelo preparado

`rac-user-service/internal/listings` prepara un snapshot completo y separado del
perfil privado: nombre, biografía, intereses, descripción, actividades/notas,
precio entero CLP, referencia de foto inmutable y área pública seleccionada.
El área no se copia desde la ciudad privada. Los identificadores admitidos y
precios requieren una política explícita: las cifras y áreas de pruebas son
sintéticas, no aprobación de D04 ni datos CUT inventados.

El preparador ordena/normaliza colecciones, calcula SHA-256 sobre JSON UTF-8
canónico propio (versión `rac-listing-payload/1`) y congela copias de payload y
evaluación. Conserva la versión de política de publicación y de analizador/léxico
por campo; cambios de versión durante una evaluación, cancelación, puntuación
inválida, spans inválidos o exceso de presupuesto fallan antes de persistir.
Contacto produce un error corregible sin fragmentos/reglas privados. Las demás
señales calculan prioridad, nunca aprobación o sanción. Una categoría no evaluada
se conserva como tal, incluso con riesgo cero.

## Persistencia

V041 agrega `listings`, `listing_revisions` y `listing_revision_decisions`.
El texto canónico es la fuente; JSONB y digest se generan en PostgreSQL sin
permitir que un servicio suministre un hash falso. El historial y decisiones son
append-only, también frente a escrituras ordinarias del migrador. Los punteros
compuestos no pueden referenciar otra publicación; publicar exige una decisión
de aprobación registrada. Decidir bloquea la misma fila que enviar una propuesta,
rechaza autorrevisión/versión desplazada y exige despejar el pendiente en la misma
transacción. Nueva propuesta y rechazo conservan el puntero publicado anterior.

Las filas antiguas reciben solo un sobre `unpublished`, sin certificar su texto
ni borrar habilidades retenidas. Un sobre sin historia puede desaparecer con el
perfil; una revisión existente requiere la futura saga auditada P12 para purgarse.
No se ha activado una retención irreversible de datos reales.

`listings.Submit` usa la transacción del dueño y verifica pertenencia por subject,
versión esperada y hash. Hace análisis fuera del bloqueo. Obtiene el siguiente
número en otra sentencia después de adquirir el lock para evitar un max obsoleto
tras esperar bajo READ COMMITTED. No hace commit: el servicio debe incorporar
auditoría/outbox y comprobar documentos, identidad y standing antes de confirmar.
Un error exige rollback de toda la operación.

## Evidencia local

Pruebas del preparador con el analizador compartido real: contacto por superficie,
ofuscación, sospecha que sigue a revisión, hash canónico, copias inmutables,
catálogo cerrado, precios inclusivos, versiones/cancelación, presupuesto y medios
externos. Se ejecutan con Go 1.27.2 y `-race`.

El ensayo de permisos pasó desde BD nueva y actualización V018 con
migrador real sin superusuario, incluyendo digest UTF-8, historial inmutable,
autorrevisión, revisión obsoleta y conservación de la aprobada
(`.local/p08-listing-database-permissions-final.log`, exit 0). Incluyó restaurar
dos revisiones/decisiones y sus digests, y rechazar punteros entre publicaciones.
El ensayo Go sobre PostgreSQL real pasó con escritura como `rac_user`, pertenencia,
rollback conjunto y dos envíos concurrentes sobre una versión
(`.local/p08-listing-migrations-user.log`, exit 0).
El conjunto se repitió desde snapshots Git fijos de infra `bd6178b`, user
`ded480c`, platform `5f1030f` y los demás pins candidatos: permisos/restauración y
migraciones/user terminaron exit 0
(`.local/rac-p08-db-proof-3d2b203f09a2/{revisions.json,permissions.log,migrations-user.log}`).
Los cinco servicios pasaron vet y `-race` con v0.15.1
(`.local/p08-rac-*-go-v0151.log`).

La auditoría de rutas además cerró una omisión P07 en POST `/api/user/profile`
y verificó los datos públicos guardados antes de ambas publicaciones, incluidos
nombres heredados del login. Ese guard conserva `FOR NO KEY UPDATE` para no
reintroducir el bloqueo FK contra sanciones. Tiene prueba PostgreSQL específica
de nombre/bio/intereses almacenados, rollback y publicación tras corrección;
se registra por separado después del primer snapshot para no atribuirle evidencia
de un código anterior.

Esa segunda prueba terminó exit 0 desde infra `72b70fb` y user `6475294`, con
platform v0.15.1 y el resto de pins fijos
(`.local/rac-p08-db-proof-6971df4067ff/{revisions.json,migrations-user.log}`).
Se exigió el PASS de `TestStoredPublicContactPostgres`: nombre, biografía e
intereses guardados se rechazan antes de crear un perfil por ambas rutas, y una
cuenta corregida con teléfono privado puede publicar. La suite de migraciones
también mantuvo adopción legacy, preservación, checksums, documentos y standing.
Todo ocurrió en contenedores desechables; los scripts retiraron sus recursos.

## Lector privado en desarrollo

La migración V042 incorpora una cola por riesgo y detalle de revisión mediante
funciones privadas. Retira a `rac_user` la facultad de insertar decisiones o
promover la revisión pública, incluidos sus permisos por columna. No provisiona
por sí sola un login de revisión ni activa rutas en el router público.

`internal/listingreview` exige audiencia `rac-user-listings`, permiso
`listings.read` y sesión staff MFA. Consulta con un login separado, limitado a
tres funciones; comprueba sus privilegios al iniciar y en cada lectura. La cola
entrega metadatos; el detalle incorpora el snapshot y sus señales. El contenido
se mantiene en memoria hasta confirmar la transacción de acceso y revalidar la
sesión. Paginación y parámetros rechazan campos repetidos, desconocidos o
incompletos. La integración de runtime y consola sigue pendiente.

El evento de auditoría identifica al servicio. El humano delegado y el recurso
consultado quedan correlacionados por ID en un registro append-only separado;
esto no constituye evidencia externa inalterable ni vinculación criptográfica
del contenido completo de ese registro. No reemplaza los trabajos P10/P15.

La suite local de user-service pasó `go vet ./...` y `go test -race -count=1
./...` (`.local/p08-reader-user-unit.log`). Las pruebas unitarias incluyen
rechazo por rol/audiencia y consultas ambiguas. La prueba PostgreSQL nueva
requiere `RAC_LISTING_REVIEW_TEST_DATABASE_URL` sobre una base desechable y está
incluida explícitamente en `test_migrations.py --services user`; un test omitido
por falta de variable no cuenta como evidencia de esa integración.

La prueba aislada PostgreSQL terminó exit 0
(`.local/p08-reader-role-probe-go.log`): cola sin contenido, detalle autorizado,
404 auditado, lectura sin entrega ni commit al vencer MFA después del SQL y
rechazo ante un permiso de columna agregado. La suite completa de permisos
también terminó exit 0 (`.local/p08-reader-database-permissions.log`): migración
sin superusuario fresh/V018, restauración y revocación efectiva de la autoridad
de moderación del servicio público. Estas pruebas no activan el lector en dev.

La regresión `test_migrations.py --services user` terminó exit 0
(`.local/p08-reader-user-migrations.log`) y exigió el PASS del lector real,
además de documentos, identidad, standing, envío de revisiones, preservación de
datos y detección de cambios de checksum. El manifiesto candidato local fija
estos commits y platform v0.16.0; el manifiesto activo de CI conserva P07 hasta
publicar y verificar coordinadamente la siguiente entrega.

## Corrección y rechazo privados en desarrollo

V043 añade catálogos de motivos versionados y sellados, decisiones negativas,
registro delegado e intención de aviso en outbox. No instala motivos ni activa un
catálogo. Un catálogo se carga en una transacción: primero sus definiciones y
después la fila revisada que lo sella. No se pueden añadir motivos a una versión
sellada ni modificar sus definiciones. Un bloqueo por versión serializa carga y
sellado. La activación y su flujo editorial siguen pendientes.

`NewCorrector` usa otro login con solo tres funciones, sin lectura de contenido,
tablas ni permiso de publicación. Su router admite POST
`/internal/listings/revisions/{id}/decisions` para `rejected` o
`changes_requested`, bajo `listings.review` y MFA. Exige ID de evento, versión
esperada como decimal en texto, hash exacto, versión de motivos y código válido;
el actor/política técnica proceden de la sesión/configuración del servidor.
No admite notas libres, fragmentos privados ni parámetros que afirmen autoridad.
La aprobación positiva no está implementada por este comando.

La decisión bloquea la publicación, impide autorrevisión, confirma que la revisión
sigue pendiente y conserva la publicación aprobada anterior, incluso al rechazar.
En la misma transacción escribe decisión, correlación humana, outbox mínimo y
`listing.reviewed` en la auditoría. La intención de aviso no equivale a entrega:
no hay consumidor de esta outbox ni correo/push activado. No crea sanciones.

Los reintentos exactos recuperan el resultado original aunque cambie o falte el
catálogo vigente; reutilizar el evento con otro actor, comando, política técnica
o login produce conflicto. Dos instancias que deciden con eventos distintos
compiten por una versión; con el mismo evento deben recibir la misma respuesta
sin duplicar efectos. Se revalidan los privilegios y MFA antes del commit.
Readiness distingue la falta de un catálogo efectivo o una fecha de revisión
futura; no anuncia un corrector operativo cuando no puede resolver peticiones.

La prueba con el login restringido reprodujo un defecto que no aparecía al usar
superusuario: las constraints diferidas de V041 ejecutaban SELECT al COMMIT tras
volver al login sin tablas. V043 cambia solo sus dos funciones de comprobación a
SECURITY DEFINER con `search_path=pg_catalog`; no concede SELECT a la API ni
reescribe V041. Se conserva la reproducción en
`.local/p08-corrector-deferred-constraint-reproduction.log`.

La prueba aislada del corrector terminó exit 0
(`.local/p08-corrector-role-probe-go.log`). Después se congelaron por Git archive
infra `5ea2e1f`, user `75c3b2c`, platform `42dbb345` (v0.16.0) y los otros seis
compañeros del manifiesto candidato. Permisos y migraciones/user terminaron
exit 0 desde ese conjunto exacto en
`.local/rac-p08-db-proof-f0fbe66fef5a/{revisions.json,permissions.log,migrations-user.log}`.
La suite exigió el PASS de ambos ingresses reales: fallos de auditoría después de
la escritura, MFA vencido después del SQL, catálogo ausente/futuro, versionado,
reintentos y dos instancias en carrera, conservando el snapshot público anterior.
También mantuvo los escenarios de documentos, identidad, standing y migraciones.
Se retiraron los contenedores desechables; no se migró ni modificó DEV.

Este ensayo no publica platform v0.16.0, no cambia los pins activos de CI y no
prueba entrega de avisos, el catálogo de motivos real ni aprobación positiva.

## Aprobación positiva en desarrollo

V045 agrega `listing_review.approval_context` y `listing_review.approve`. No
provisiona un login, no aprueba categorías D04 ni conecta lecturas públicas.
`NewApprover` usa un tercer login limitado a `ready`, contexto y aprobación: sin
lectura de contenido, tablas ni corrección. POST
`/internal/listings/revisions/{id}/approval` exige `listings.review` y MFA, ID de
evento, versión esperada decimal y hash exacto; no admite motivo, nota ni
requisitos enviados por el cliente.

La transacción de aprobación bloquea primero la publicación. Después user-service
evalúa documentos, declaración compa e identidad del dueño con su propia
credencial, en otra transacción que conserva sus bloqueos compartidos (registro
de documentos) hasta el commit de la aprobación. La función revalida bajo el
mismo bloqueo: revisión pendiente, versión y hash, autorrevisión, estado de la
publicación, misma versión de política de publicación que el envío, standing
activo sin restricción `publish_listing` (bloqueado FOR SHARE), cada actividad
activa, sin verificación adicional pendiente y aprobada, y ninguna foto. Las
actividades `proposed` solo se aceptan si la configuración del servidor lo
permite (dev/test). Una foto referenciada falla con `listing_photo_unapproved`
hasta que P09 promueva medios revisados. Cada fallo de estado responde 409 con su
código y no escribe nada.

En la misma transacción se escriben decisión `approved`, punteros publicados,
evento con los requisitos efectivamente evaluados (un control desactivado queda
`false`, no aprobado), outbox mínimo y `listing.reviewed` en auditoría. Un
reintento exacto devuelve el resultado original sin reevaluar al dueño; otro
humano, login, política o comando con el mismo evento produce conflicto. Dos
instancias con eventos distintos producen una sola aprobación; la publicación
aprobada anterior sigue pública mientras un nuevo envío está pendiente.

`TestApprovalPostgresHTTP` pasó dentro de `test_migrations.py --services user`
(`.local/p08-approval-migrations-user.log`, exit 0): foto, hash/versión, autorrevisión,
rol sin revisión, catálogo propuesto fuera de dev, cambio de política, requisitos
del dueño ausentes/no disponibles, restricción, suspensión, actividad retirada,
fallo de auditoría tras las escrituras, MFA vencido tras el SQL, replay, carrera
de dos instancias y deriva de privilegios. El ensayo sin superusuario fresh/V018
también terminó exit 0 (`.local/p08-approval-database-permissions.log`) y comprueba
que ningún rol de servicio puede ejecutar las funciones de aprobación. Nada se
aplicó a DEV.

## Envío y estado del dueño en desarrollo

POST `/api/user/me/listing/submissions` (rol compa, mismos gates de documentos e
identidad que `PUT /me/compa`) recibe versión esperada y borrador. Analiza fuera
de cualquier bloqueo; contacto público es un rechazo corregible con el campo, el
resto de señales solo prioriza revisión. Dentro de la transacción del dueño
aplica standing, guarda la revisión con `listings.Submit`, revalida documentos y
el permiso de standing antes del commit. Nunca publica: la publicación aprobada
anterior sigue vigente hasta que un humano apruebe la nueva. Responde 202
`submitted`, sin la palabra "publicar".

La política de publicación (`LISTING_POLICY_VERSION`, límites de precio, áreas)
no tiene valores por defecto porque D04 no fija importes ni categorías definitivas, y el léxico propuesto
solo se admite en dev/test (D13); fuera de eso el envío responde 503
`listing_submission_unavailable`. La aprobación debe configurarse con la misma
versión de política. Una foto se rechaza con 409 `listing_photo_unavailable`
hasta que P09 promueva medios revisados. El envío no agrega un evento de
auditoría: el vocabulario de `audit.log` no tiene acción para envíos y la
revisión append-only es el registro del acto del dueño.

GET `/api/user/me/listing` devuelve estado, versión, snapshots pendiente y
publicado del propio dueño y la última decisión (código de motivo y clave de
nota). No expone señales, riesgo ni identidad del revisor. Contrato en
`rac-shared-contracts` `4284002`.

`TestListingOwnerPostgres` pasó como `rac_user` dentro de
`test_migrations.py --services user` (`.local/p08-owner-migrations-user.log`,
exit 0): política ausente, foto, contacto, actividad fuera de catálogo, precio,
versión mal formada, campo desconocido, envío y reenvío con conflicto de
versión, ausencia de publicación directa, estado del dueño sin campos privados
y cuenta sin perfil compa.

## Activación privada DEV de los ingresses de revisión

`listingreview.FromEnvironment` sirve lector, corrector y aprobador en `:8084`
solo con `LISTING_REVIEW_ENABLED=true`; un valor ambiguo detiene el servicio.
Exige tres URLs distintas, una por login, y `/ready` requiere las tres (sin
catálogo de motivos efectivo queda no listo). El puerto no se publica.

`make listing-review-db-config ENV=dev STANDING_PREVIEW=1 LISTING_PREVIEW=1`
provisiona `rac_listing_reader`, `rac_listing_corrector` y
`rac_listing_approver` solo en DEV, con secretos independientes entre sí y de
los roles existentes, exactamente tres funciones cada uno y principal de
auditoría propio. Rechaza un rol existente con columnas, tablas u otras
funciones. `compose.listings.yaml` exige además política técnica, versión de
política de publicación y precios sintéticos elegidos por el operador: no son
D04. No crea cuentas staff, no siembra motivos ni aprueba categorías.

`test_database_permissions.py` lo comprobó fresh/V018 sin superusuario
(`.local/p08-listing-provision-permissions.log`, exit 0); el render de compose y
la puerta del Makefile tienen pruebas unitarias. No se activó en DEV.

El mismo overlay habilita en admin `LISTING_REVIEW_PROXY_ENABLED` hacia
`http://backend-user:8084` (admin `6b017a1`). Las rutas
`/api/admin/staff/listings/{queue,revisions/:id,revisions/:id/decisions,revisions/:id/approval}`
reenvían solo `limit`/`cursor` y la autorización; validan `event_id`, exigen que
la respuesta repita revisión y evento y solo dejan pasar códigos de error de una
lista cerrada (el resto es 503). El cliente Keycloak `rac-staff` agrega la
audiencia `rac-user-listings` y reconcilia mappers en clientes existentes; la
prueba con Keycloak real lo verificó
(`.local/p08-identity-listings-audience.log`, exit 0).

La consola staff de Flutter muestra la cola y el detalle con `listings.read` y
aprueba con `listings.review`. Las señales se presentan como orden de revisión,
no como prueba. La aprobación envía un único comando congelado; ante un
resultado incierto, reintentar reenvía el mismo evento. Rechazar o pedir cambios
queda sin interfaz hasta tener un catálogo de motivos revisado (D06). Suite
completa 254 tests, analyze y build web en `.local/p08-listing-console-flutter.log`.

## Corte pendiente para completar P08

1. Hecho en desarrollo: envío y estado del dueño (sección anterior). Una fila de
   decisión SQL no prueba por sí sola que un humano autorizado la emitió.
2. Hecho en desarrollo (V045, sección anterior): revalidación al aprobar con
   carreras y rollback. Logins DEV provisionables (sección anterior). Falta la
   foto aprobada de P09; hoy cualquier foto bloquea la aprobación.
3. Corte coordinado de TODAS las lecturas públicas, descubrimiento y medios a
   snapshots aprobados, y retirada de rutas mutables alternativas. Cambiar un
   nombre, biografía o foto no puede alterar una publicación ya aprobada.
4. Flutter del dueño hecho en desarrollo (`/listing-review`, frontend `dbd93fd`):
   envía el perfil guardado, muestra pendiente/aprobado/rechazado/cambios, no
   promete plazos (D07) ni usa "Publicar". Suite completa 249 tests, analyze y
   build web en `.local/p08-listing-review-flutter.log`. Falta la consola de cola
   y decisión para staff (A4, hecha para aprobar; falta rechazo con motivos) y
   una prueba de navegador del flujo completo.
5. Resolver referencias de foto/P09 antes del corte: cambiar/borrar una foto
   personal no puede sustituir un objeto aprobado ni dejar una URL pública viva.
   La base de fuentes privadas y sus límites consta en [P09-photos.md](P09-photos.md);
   no se confunde confirmar bytes de una subida con aprobar una foto.
6. Laboratorio integrado y matriz de autorización de cada ruta, versión obsoleta,
   rechazo, retirada de categoría, política de precio, KYC/standing y medios.

P07 aún necesita corpus humano, paridad de reglas públicas, política/léxico
persistidos y hot reload. Se reprodujo un defecto previo a ese reload: `New`
retenía el slice original y una mutación podía retirar `minors` de la lista no
evaluada sin agregar reglas reales. También aceptaba pesos NaN y dependía de una
lista pública mutable de categorías. La corrección publicada v0.15.1 (`5f1030f`)
congela las reglas, aísla categorías internas y rechaza pesos no finitos.
Reproducción fallida en `.local/p07-lexicon-snapshot-reproduction.log`; suite
completa con `-race` y caso concurrente pasaron en
`.local/p07-lexicon-snapshot-final.log`. No se reescribió v0.15.0.
