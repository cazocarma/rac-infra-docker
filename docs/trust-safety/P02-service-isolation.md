# P02 — Aislamiento de credenciales y privilegios

Implementación local, 2026-10-22. Rama `feat/service-isolation`, sobre P01 en
infra y sobre los HEAD inspeccionados de user/chat. Las revisiones coordinadas
son user `ddd8a39` y chat `1cdd512`, fijadas en companion-revisions.json. No se desplegó al stack DEV,
no se hizo push y no se modificaron permisos de GitHub.

## PostgreSQL

Se retira la URL compartida de aplicación de las plantillas. Cada proceso recibe
solo su `DATABASE_URL` propia. Un job operador `database-config`, previo a Flyway,
crea los logins, instala extensiones que requieren privilegios y transfiere los
objetos RAC existentes al migrador sin usar `REASSIGN OWNED`. No cambia dueño de
objetos compartidos del cluster ni de extensiones o la BD de Keycloak.

`rac_migrator` posee el DDL de RAC, sin SUPERUSER, CREATEROLE, CREATEDB,
REPLICATION ni BYPASSRLS. Las APIs tampoco tienen estos atributos ni CREATE/TEMP.
Se rechazan roles preexistentes con atributos o membresías inesperadas; no se
revocan silenciosamente privilegios de una cuenta de operador ajena.

| Proceso | Login / configuración | Alcance |
|---|---|---|
| backend-user | rac_user / USER_DB_URL | Perfil, compa, skills y reseñas; alta/edición de disponibilidad del onboarding actual; reservas en lectura y lock acotado |
| backend-match | rac_match / MATCH_DB_URL | Reservas, disponibilidad, excepciones y cupos; suscripción en lectura |
| backend-chat | rac_chat / CHAT_DB_URL | Mensajes, bloqueos/reportes/auditoría actuales; reservas sin UPDATE |
| backend-alert | rac_alert / ALERT_DB_URL | Lee notificaciones, actualiza solo leido_en |
| booking-maintenance | rac_maintenance / MAINTENANCE_DB_URL | Estado/fecha de actualización de reservas; no perfiles ni mensajes |
| booking-events-relay | rac_relay / RELAY_DB_URL | Lee outbox, actualiza solo intentos/publicación/reintento |
| alert-events-consumer | rac_alert_consumer / ALERT_CONSUMER_DB_URL | Inbox, cuarentena, notificaciones; identidad/participantes mínimos en lectura |
| identity-config | rac_seed / IDENTITY_DB_URL | Semillas DEV; sin acceso a mensajes |
| backups | rac_backup / BACKUP_DB_URL | Lectura de RAC y schema kc; sin escritura ni pg_authid |
| auth/admin | Sin credencial PostgreSQL | OIDC / agregación por APIs |

La V019 contiene grants explícitos por tabla/columna. Se retira EXECUTE público
de funciones de aplicación; las funciones de extensiones conservan su contrato.
Los disparadores de integridad/outbox que cruzan dueños ejecutan con propietario
restringido y search_path fijo, sin conceder escritura directa del outbox a la API.
La función `lock_booking(uuid,text,boolean)` conserva locks de chat y reseñas,
verifica participación antes de bloquear y no expone una operación UPDATE.
User/chat siguen comprobando la identidad del JWT y la propiedad del recurso.

El aislamiento es por servicio, no una política RLS por usuario ni una
prohibición de todas las lecturas entre dominios. Se mantienen las lecturas
mínimas requeridas por el modelo actual. La autorización de capacidades/standing
seguirá en P03. El registro de chat aún se reemplazará de forma coordinada en P11.

## Keycloak

Se fija 26.8.1 por digest
`sha256:79c623a22abacf3fe6c00a5fb30f5b7843d717b234033b80995891c06116d244`.
Se usa FGAP v2 y se retiran manage-users/view-realm y sus scope mappings de la
cuenta técnica. La política permite mapear únicamente compa; no le permite
editar usuarios, resetear contraseñas, gestionar clientes ni otro realm.
La [documentación oficial](https://www.keycloak.org/docs/26.8.1/server_admin/)
describe la delegación mediante el cliente admin-permissions y scopes de usuario
y rol. Las pruebas locales verifican los permisos efectivos, no solo el JSON.

El backend ya no consulta `/roles/compa`, que exigiría acceso adicional.
identity-config escribe el UUID del rol en un volumen; backend-user lo monta
de solo lectura. El adaptador fija el nombre compa y rechaza configuración
ausente o inválida. Keycloak verifica conjuntamente ID/nombre y sus permisos.
El archivo no contiene secretos ni habilita asignar otro rol.

Se configura expiración de access tokens de cinco minutos, rotación de refresh
tokens sin reutilización, protección de intentos y política de contraseña.
DEV conserva la excepción de contraseña de seis caracteres para las fixtures
ya existentes; QA/PRD exigen doce y complejidad. Verificación de correo requerida
en QA/PRD necesita correo operativo antes de abrir registro real. No se activan
proveedores de correo en esta entrega.

## Staff y MFA

Nuevo cliente separado rac-staff, roles de cliente ts_agent, ts_lead, legal,
support y business_admin; ningún usuario recibe esos roles automáticamente.
Se prepara un flujo contraseña+OTP obligatorio, PKCE S256 y mapper AMR de
ejecuciones completadas, sin fabricar un claim MFA por tener un rol.

La prueba por HTTPS demuestra que contraseña sola no completa autorización;
OTP válido permite obtener un token con amr pwd/otp, azp rac-staff y auth_time.
El cliente queda **deshabilitado** en la configuración final: el alta de staff,
enrolamiento supervisado, consola, AccessGuard y verificación de frescura por
endpoint dependen de D10 y de las entregas posteriores. Los endpoints admin
existentes no adquieren protección MFA por crear este cliente. No se anuncia
una consola sensible ya habilitada.

Las pruebas usan un certificado efímero de localhost validado mediante CA
explícita. No se desactiva validación TLS ni se fuerzan cookies Secure sobre HTTP
para hacer pasar el login.

## Respaldos y restauración

Backups usa rac_backup, no el operador PostgreSQL. Lee schemas de aplicación
(incluidos los datos de configuración de PostGIS) y kc; sin rol global de lectura
de catálogos ni acceso a hashes de contraseña. Se configura lectura por defecto
para tablas futuras del migrador y de Keycloak. `pg_dumpall --no-role-passwords`
preserva definiciones/ACL sin incluir hashes de credenciales.

Después de restaurar, las credenciales vigentes se reprovisionan desde su
custodia; no se recuperan contraseñas del dump. El ensayo desechable restaura
los datos y verifica que chat conserva INSERT de mensaje sin UPDATE de reserva.
El runbook general de restauración aislada sigue vigente. Tombstones, holds,
anclaje independiente y copias fuera del PC continúan pendientes de P12/D11;
no se activan aquí.

## Activación DEV y reversa

**Antes de iniciar 26 sobre un volumen existente:** detener escritores y jobs,
obtener respaldo cifrado consistente de RAC, Keycloak y fotos, registrar el
snapshot y ensayar recuperación aislada. La prueba sintética 24→26 no reemplaza
el respaldo de tus datos locales. Esta entrega no ejecutó esa actualización.

1. Guardar las revisiones coordinadas de infra/user/chat y los archivos de entorno
   fuera de Git. Conservar el snapshot previo y los secretos bajo custodia separada.
2. Ejecutar `make database-init` en DEV. Genera secretos independientes, conserva
   comentarios/otros ajustes, retira DATABASE_URL compartida y no imprime valores.
   QA/PRD requieren credenciales del operador; el generador rechaza esos entornos.
3. Aplicar el conjunto coordinado: database-config, Flyway V018/V019, Keycloak,
   backends nuevos e identity-config. `make up` ordena la inicialización; ejecutarlo
   solo tras completar el respaldo y la recuperación anterior. Las herramientas
   de pruebas con privilegios de migrador están limitadas a DEV.
4. Probar PKCE/redirect, publicación compa, reserva, mensajes, reseña, notificaciones
   y nuevo respaldo/restauración antes de reabrir escritores o dar la unidad por
   activada. Nunca publicar el contenido de `.env` o `compose config`.

No volver a arrancar Keycloak 24 contra una BD ya migrada a 26. La reversa de esa
actualización requiere restaurar el snapshot compatible y las revisiones previas
en ventana controlada. No editar V019 ni eliminar auditoría para revertir: usar
compensación forward o restauración coordinada, preservando nuevas evidencias.
Volver al backend user anterior tampoco es transparente: intentaría la consulta
de roles que la cuenta técnica ya no puede hacer.

La topología presupone un cluster Compose separado por ambiente. No compartir
el mismo cluster entre dev/qa/prd con estos nombres de login sin rediseñar la
provisión: los roles PostgreSQL son globales al cluster.

## Pruebas y reproducción

Resultados locales con recursos únicos desechables y sin `.env` real:

- V019 fresh y upgrade desde V018 mediante Flyway sin superusuario: PASS.
- Permisos negativos, locks, triggers, outboxes, reseñas y notificaciones: PASS.
- Dump/restore con ACL y sin hashes de contraseña: PASS.
- Keycloak FGAP v2: asignación compa positiva; admin/usuarios/password/realm 403: PASS.
- Login staff contraseña+OTP+PKCE y AMR efectivo por HTTPS: PASS.
- Upgrade PostgreSQL persistido Keycloak 24→26.8.1, IDs/credenciales/clientes y theme RAC: PASS.
- Go vet y go test -race de user/chat: PASS; regresiones de migraciones/cupos/chat/publicación: PASS.
- Modelos Compose dev/qa/prd, separación de backups, gates de deploy y política de Actions: PASS.

```sh
make test-database-permissions
make test-identity-permissions
python scripts/test_keycloak_upgrade.py
python scripts/test_migrations.py
python -m unittest discover -s scripts -p 'test_database_credentials.py'
python scripts/check_configuration.py
python scripts/check_backup_configuration.py
```

Docker, Python estándar y OpenSSL son suficientes para estas pruebas; los drivers
y Go se ejecutan en contenedores. CI incluye los mismos gates, con timeout acotado;
no hay resultado remoto afirmado. La promoción cubre ahora todos los scripts
Python y el theme Keycloak en su hash de infraestructura, incluyendo la provisión nueva.
