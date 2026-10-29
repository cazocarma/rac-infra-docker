# Provisión editorial DEV — validación local

La provisión de base de datos está separada de `editorial_lab_fixture.py`.
`scripts/editorial_database.py` no crea usuarios de Keycloak, no asigna roles
humanos, no habilita listeners ni publica documentos o activa políticas.

Precondiciones: migraciones V034–V037 aplicadas mediante el migrador separado,
respaldo/recuperación de DEV revisados y conexión de operador controlada.
No ejecutar contra DEV por inferir autorización de una prueba desechable.
QA/PRD permanecen fuera de este adaptador: rechaza RAC_ENV distinto de dev.

Preparar fuera de Git `DOCUMENT_EDITORIAL_DATABASE_URL` con identidad fija
rac_documents_editorial y secreto independiente de al menos 24 caracteres.
El destino debe ser la base RAC seleccionada, host interno postgres, puerto
5432 y sslmode=disable exclusivamente en esta red DEV. No usar este transporte
en un ambiente productivo ni modificar la validación para aceptar URLs ajenas.
La variable se entrega por el entorno del proceso; no escribir su valor como
argumento, salida de consola o ejemplo versionado.
La CLI exige la configuración completa de las identidades normales, la valida
y compara sus secretos decodificados con el editorial antes de conectar.
También rechaza coincidencia con los secretos de operador/Keycloak presentes
en el entorno. No descubre ni afirma verificar secretos externos no provistos.

## Overlay de activación explícita

`compose.editorial.yaml` se selecciona únicamente con EDITORIAL_PREVIEW=1,
ENV=dev y STANDING_PREVIEW=1. Por defecto no se incorpora. Make rechaza QA/PRD,
valores ambiguos y activación sin standing. El overlay activa juntos el gate
documental de user/match/chat, el lector técnico configurado por identity-config
y los endpoints editoriales de user/admin. Mantiene privados 8082/8083 y fija
el destino del proxy en backend-user:8083. No agrega usuarios o servicios fixture.

Primero provisionar la BD con el preview editorial apagado; después preparar
DOCUMENT_EDITORIAL_POLICY_VERSION como UUID de la política revisada y la misma
credencial editorial por el canal de secretos acordado. El overlay exige ambos
valores al componer. Un registro vacío no se rellena: las acciones comerciales
quedan cerradas hasta una publicación/activación aprobada. Los derechos deben
permanecer accesibles según los controles ya implementados.

Esto no es una orden de aplicar up: falta preparar la identidad humana y aplicar
la activación controlada del cliente rac-staff. identity-config lo deja apagado
por defecto. STAFF_CLIENT_ENABLED=true es una opción separada y explícita,
aceptada únicamente en DEV con standing y documentos habilitados. Reconciliar
repetidamente conserva ese estado deseado sin quitar OTP, PKCE, audiencia
limitada ni límites de sesión; tampoco asigna roles a personas.

Volver a false deshabilita el cliente para nuevos accesos/renovaciones. No
equivale a revocar inmediatamente JWT ya emitidos: conservan su vencimiento
original. Para retirar acceso de inmediato hay que cerrar también las rutas
staff/editorial y aplicar el procedimiento de sesiones/revocación revisado,
sin anunciar que cambiar una opción de cliente invalida por sí solo todo token.
El despliegue coherente de revisiones y la aplicación sobre DEV persistente
siguen pendientes. QA/PRD no utilizan este transporte interno sin TLS.

Dos pruebas de test_editorial_compose.py pasan: condiciones reales de Make en
dry-run y merge de Docker Compose con valores sintéticos. Verifican defaults,
dependencias, destinos fijos y ausencia de publicación de puertos internos.
No arrancan contenedores ni leen el archivo privado de ambiente DEV.

Dos pruebas de test_staff_activation.py comprueban defaults, opciones estrictas
y rechazo antes de llamadas admin si enabled no es booleano. Los trece tests
de provisión/fixture/activación/Compose/aislamiento se incorporaron al workflow
de CI y pasan localmente. El ensayo Keycloak real terminó con salida 0 en
.local/p04-staff-client-reconciliation.log: se reconcilia encendido dos veces,
se conserva el flujo obligatorio de contraseña/OTP, se prueba el token staff y
se vuelve a apagar el cliente al terminar. No se modificó el realm DEV.

Invocación explícita desde infra: `make editorial-db-config ENV=dev`.
El target construye la imagen de herramientas y hereda la variable por nombre;
no se ejecuta como parte de up ni de la migración general. Después de crear la
identidad, abre una conexión con ella y verifica editorial_ready(). Los flags
DOCUMENT_EDITORIAL_ENABLED y STAFF_ACCESS_ENABLED continúan como estaban.

El operador exige transacción sobre la base exacta y privilegio de operador,
once funciones con firmas exactas, ausencia de membresías y de permisos sobre
tablas, columnas, creación en schemas o activación/auditoría crudas. Rechaza
autoridad inesperada en vez de intentar corregirla silenciosamente. Concede
CONNECT, USAGE y EXECUTE solo para el flujo editorial tipado. Repetir conserva
actor/cadena de auditoría; no crea otra cadena ni cambia decisiones históricas.

El provisionador verifica además los grants explícitos de funciones en los
esquemas de aplicación: sus OID deben pertenecer a las once firmas previstas.
Incluye autoridad por propiedad de función. La API editorial aplica la misma
condición al arrancar y comprueba permisos por columna y CREATE en schemas,
además de las restricciones anteriores. No se afirma vigilancia continua de
cambios de ACL tras el arranque ni se sustituye la revisión de grants PUBLIC.

El proceso usa el secreto recibido para reconciliar la credencial. Una rotación
requiere coordinar la nueva credencial con el listener y probar reconexión; no
cambiarla unilateralmente mientras un servicio dependa de la anterior. Los
errores de CLI son genéricos y no imprimen DSN, secreto ni diagnóstico servidor.

Tres pruebas de validación pasan en test_editorial_database.py. Ensayo real
fresh/upgrade, repetición, rechazo de permiso por columna y conservación de
actor/cadena aprobado en .local/p04-editorial-operator-permissions-final.log.
La ampliación de separación de secretos se verifica ahora en
.local/p04-editorial-operator-separated-secrets.log; terminó con salida 0,
incluidas las conexiones reales con configuración completa y los permisos
negativos del ensayo. No quedan procesos pendientes de esta verificación.
Este documento no
configura la identidad humana/MFA ni aprueba QA/PRD.

## Candidato de revisiones coordinadas

`ci/p04-companion-candidate.json` registra ocho commits completos de los
compañeros. Es separado de `ci/companion-revisions.json`, la
entrada activa de CI; crear el candidato no publica fuentes ni cambia checkouts
remotos. Contratos permanece en a1ad086a8569ea1bba68c94679026111c42045d5 y las
migraciones hasta V038 pertenecen al commit de infra que contiene el candidato.

`make check-p04-candidate` es de solo lectura y sin red. Exige HEAD exacto y
checkout limpio por compañero, una misma versión estable de rac-platform en
los cinco consumidores, metadata de vendor coincidente y tag que resuelva al
commit fijado de platform. Rechaza replace local. Pasó sobre los ocho clones
actuales, todos limpios, con v0.13.0. Su prueba cubre HEAD, dirty, vendor,
versiones divergentes, reemplazo y tag incorrectos, y está incorporada en CI.

No comprueba todo el contenido de vendor, disponibilidad remota, imágenes ni
compatibilidad integrada; esos gates siguen separados. Antes de promover el
candidato a entrada activa hay que publicar las revisiones necesarias, verificar
su lectura con la App y ensayar ese conjunto. No actualizar pins remotos con
commits todavía inaccesibles ni usar un CI verde del manifiesto antiguo como
evidencia del nuevo conjunto.

### Publicación coordinada de ramas (2026-10-29)

Tras fetch de los diez repositorios se confirmó PR infra #9 en draft, remoto
752e9b1, con cambios locales posteriores. Solo auth del candidato estaba contenido
en una rama remota. Se publicaron primero platform 535006e y su tag inmutable
v0.13.0; después las ramas de user, match, chat, alert, admin, Flutter y contratos.
Todos los pushes fueron fast-forward, sin force, merge ni despliegue.

El manifiesto activo se actualizó al candidato ya publicado. El verificador de
HEAD/módulo/vendor/tag y check_go_vendor.py pasaron sobre esas revisiones.
make test-workflows también pasó localmente antes de publicar. La publicación de
infra y el CI integrado nuevo deben comprobar todavía la lectura con la App y
el resultado del conjunto; SSH del operador no demuestra permisos de la App.
Los resultados anteriores de GitHub corresponden al manifiesto antiguo.

El endurecimiento adicional de funciones/columnas/CREATE pasa las pruebas Go
focalizadas con race en .local/p04-editorial-capability-unit.log. Su verificación
PostgreSQL conectada terminó con salida 0 en .local/p04-editorial-capability-permissions.log
y .local/p04-editorial-capability-migrations.log. Se inyectan permisos adicionales en bases
desechables, se exige rechazo y se comprueba después la identidad mínima válida.

### Verificación posterior y regresión de concurrencia (2026-10-29)

El CI integrado 40933374690 del commit infra 86eee6e verificó acceso a los
repositorios mediante la App, políticas de workflows, almacenamiento y migraciones.
La integración falló en `commit_races`: guardar el perfil devolvió 503
`profile_unavailable` donde la carrera de sanción exige 403 y rollback.
No constituye validación del conjunto ni cierre de P04.

La consulta que serializa la edición personal usa ahora `FOR NO KEY UPDATE` en
la copia local de user: mantiene exclusión entre editores sin impedir el
`KEY SHARE` de la FK al registrar el efecto de revocación de sesiones de una
sanción concurrente. El bloqueo anterior `FOR UPDATE` podía impedir ese registro
hasta agotar el permiso temporal del editor. La reproducción del conjunto previo
y la verificación del cambio se ejecutan en laboratorios desechables; no se
amplió el plazo del permiso ni se relajó el 403 esperado. Pendiente registrar
los resultados antes de publicar esta corrección. La reproducción local del
conjunto anterior terminó con el mismo 503 en
`.local/p04-standing-race-reproduction.log`. También se cambió el bloqueo de
onboarding y sustitución/eliminación de fotos: ninguno modifica la clave
referenciada. La matriz de carreras agrega publicación Compa y sustitución de
foto a las ediciones personales, agenda y chat en ambas instancias; conserva
el 403 y comprueba rollback de los valores originales. La ejecución corregida
terminó con salida 0 en `.local/p04-standing-race-fixed.log`, incluyendo
caídas de broker/autoridad, recuperación, tokens originales y deduplicación.
User 1cc239d contiene la corrección. Esto no sustituye la medición adicional
de 100 revocaciones concurrentes ni el CI del conjunto publicado.
Los manifiestos locales avanzan a user 1cc239d y frontend 4671ce4 para
verificar ese candidato. `check_local_revisions.py` pasa con los ocho HEAD
limpios, metadatos vendor, versión común y tag inmutable. Estas nuevas
revisiones aún no se publicaron: no enviar infra antes de publicar sus
dependencias y no confundir los pins locales con los usados por el CI anterior.

La medición posterior de 40777a3 terminó con salida 0 y reporte `complete`,
`lab_completed=true`, 100 transiciones y `hot_acquisition.gate_passed=true`:
`.local/p04-standing-race-measured.json` y `.local/p04-standing-race-measured.log`.
El reporte fija los cinco SHA backend realmente construidos, incluido user
1cc239d. El gate no prueba pantallas ni los cambios posteriores de frontend.
`make test-workflows` también pasa en `.local/p04-profile-lock-workflows.log`.
Frontend avanza después a 1604d17, con análisis/150 pruebas/build web propios
en `.local/p04-notifications-localization-full.log`; los pins locales se
actualizan antes de publicar, sin repetir la medición de backend sin cambios.

Frontend 4671ce4 pasó `flutter analyze`, 146 pruebas y compilación web release
desde un archivo Git de esa revisión. Evidencia local:
`.local/p04-document-localization-full.log`. Incluye localización es/en del
lector de documentos y rechazo de tipo, versión o idioma inconsistentes con
los metadatos, incluso si coinciden ID y hash. Conserva el contenido legal
servido y la aceptación explícita. Las nuevas cadenas siguen pendientes de
revisión editorial; las pruebas técnicas no aprueban textos jurídicos.
