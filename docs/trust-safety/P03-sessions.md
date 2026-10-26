# P03 — Efecto durable sobre sesiones de identidad

El servicio user es dueño del journal y del worker; infra versiona V027,
las credenciales, el proveedor acotado de Keycloak y el overlay opt-in.
La decisión y sus límites están en [ADR-009](ADR-009-session-revocation.md).
Esta entrega sigue en validación: no activa el DEV persistente.

## Orden y recuperación

La misma transacción auditada que cambia standing agrega un efecto para
`suspended`/`banned` y cerca los efectos anteriores pendientes. El worker reclama
trabajo mediante una función SQL, con token aleatorio y lease de diez segundos.
Captura los identificadores online/offline y los persiste bajo el bloqueo de la
cuenta autoritativa, comprobando versión, estado y propiedad del claim.
La petición a Keycloak sucede después del commit y fuera de toda transacción SQL.

Cada paso revoca como máximo 32 identificadores ya guardados. Una respuesta
perdida repite esos mismos identificadores; no vuelve a enumerar sesiones.
El cursor solo avanza con el claim vigente y tras un ACK completo. El backoff
persistido crece hasta 32 segundos. Reiniciar el proceso no pierde captura,
cursor ni reintentos. Un inventario incompleto o superior a 4096 entradas falla
cerrado y conserva el efecto pendiente, sin presentar una revocación parcial
como completa.

Si una reversión confirma antes de guardar la captura, el guardado se rechaza
y no hay mutación remota. Si confirma después, un acceso creado tras la
reversión queda fuera del conjunto inmutable. Una petición antigua en vuelo
puede terminar de revocar sesiones de ese conjunto, pero no un acceso nuevo.
La garantía no depende de sincronizar relojes entre PostgreSQL y Keycloak.

## Fronteras de acceso

`rac_standing_sessions` solo ejecuta las funciones acotadas del journal. No
puede consultar tablas de usuarios, auditoría, autoridad ni journal, cambiar
standing o administrar roles. El proceso comprueba su identidad SQL al iniciar.
La API user no recibe el secreto OAuth ni privilegios nuevos sobre el journal.

El contenedor del worker usa UID/GID 10001, filesystem de solo lectura, sin
capacidades Linux ni escalamiento de privilegios. Solo monta su volumen privado
de credencial en modo lectura. El provisionador conserva el secreto y asigna
archivo 0400/directorio 0700 a ese UID. Nunca se imprime en logs o reportes.

El token técnico tiene audiencia/rol exclusivos y no concede gestión de usuarios.
Los endpoints del proveedor validan la cuenta de servicio, realm, audiencia,
cliente y rol. Readiness usa `/rac-sessions/status`, sin enumerar un usuario
ficticio. El transporte exige TLS salvo el permiso HTTP explícito del preview DEV.

## Operación y evidencia

`/health` informa vida del proceso. `/ready` exige una observación reciente de
PostgreSQL y del endpoint autenticado de Keycloak, con atraso menor a 30 segundos.
Las verificaciones se realizan cada cinco segundos; una observación de más de
diez segundos no autoriza readiness. Cada paso tiene timeout de seis segundos.
SIGTERM cancela las operaciones y cierra el servidor; un claim abandonado vence.

`/metrics` publica contadores de pasos/errores y gauges de pendientes/antigüedad,
sin identificadores de usuarios o sesiones como etiquetas. El puerto no se
publica al host y no hay ruta pública en nginx.

Validaciones locales del 26-10-2026:

- `go vet` y `go test -race` del cliente y worker pasan.
- `test_migrations.py --services user` pasa sobre bases desechables: captura
  durable, pérdida de ACK, reconstrucción del worker, reversión antes/después
  del guardado, claims concurrentes, expiración, fencing, bloqueo real de la
  autoridad y denegación de permisos. También pasa adopción y checksum drift.
- `test_database_permissions.py` pasa fresh/upgrade con Flyway sin superusuario,
  bootstrap repetido, dump sin contraseñas y restore aislado, incluyendo V027.
- `test_session_control.py` pasa con dos nodos reales, TLS y PKCE, el endpoint
  autenticado de status, sesiones online/offline, permisos negativos y reinicio.

El ensayo Compose conectado también pasó el 26-10-2026: sanción automática con
refresh online/offline reales, caída de Keycloak, journal pendiente y readiness
503/liveness 200, reinicio del worker y recuperación tras restaurar Keycloak.
La matriz existente de JWT anterior, dos instancias, escritores, carreras de
commit, fallas de broker/autoridad y derechos protectores siguió pasando.
DEV/QA/PRD y la frontera privada del worker pasan `check_configuration.py`.
Falta el CI de la revisión final y los demás gates de cierre de P03.
Estas bases desechables no sustituyen el backup/restore del DEV persistente
previo al rollout. No ejecutar el overlay sobre ese estado solo por haber pasado
las pruebas unitarias o la validación aislada del proveedor.
