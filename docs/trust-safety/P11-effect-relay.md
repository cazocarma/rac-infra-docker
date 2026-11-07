# P11 — núcleo de publicación de efectos T&S

Estado: protocolo SQL y librería Go preparados; sin adapter AMQP, proceso worker,
credenciales operativas ni activación. No se declara transporte integrado o P11
cerrado. El consumidor de user y el intake público siguen pendientes.

## Dueños y contrato

Admin es dueño de `ts.outbox` y del núcleo `internal/tsrelay` en
`rac-admin-service`. Solo publica decisiones efectivas ya registradas; no decide
sanciones, interpreta reportes ni escribe standing, reservas o chat.

`event_id` es el identificador estable del outbox; tipo/routing key preparado
`ts.action.effective.v1`, exchange preparado `rac.trust_safety`. El payload
original se conserva: no se fabrica otro evento al reintentar. La identidad del
sujeto es el principal canónico de Keycloak definido en V058 y en el contrato.

V059 separa estado operativo en `ts.effect_delivery_state`: intentos, siguiente
intento, token/xid de la toma y confirmación. Comandos del outbox y confirmaciones
completadas quedan protegidos frente a cambios y borrados. Los eventos anteriores
reciben estado pendiente; no se asume que se publicaron.

## Protocolo de transacción

El login previsto solo ejecuta cinco funciones:

- `ts.effect_relay_ready()`
- `ts.claim_effect(audit.reference)`
- `ts.confirm_effect(audit.reference)`
- `ts.retry_effect(audit.reference)`
- `ts.effect_relay_backlog()`

`New` comprueba el aislamiento del login y V059. El publisher no consulta tablas
de otro dueño; el futuro consumidor debe comprobar V058 en su propia frontera.

La toma bloquea una fila operativa con `SKIP LOCKED`. Una fila anterior sin
confirmar bloquea sucesoras del mismo principal; otros principales progresan.
El emisor toma un lock transaccional por principal antes de asignar el ID del
outbox, incluso entre casos distintos: una transacción posterior no puede
publicar primero mientras su predecesora aún es invisible por no haber hecho
commit. No se infiere orden de commit de un contador asignado sin serialización.
La llamada del publisher tiene cinco segundos dentro de una transacción de ocho
segundos. No se mantienen locks sobre casos, usuarios o reservas durante I/O.

Confirmación y reintento exigen el token y el xid de la misma transacción que
tomó la fila. Otro proceso/transacción no puede confirmar una toma abandonada ni
reiniciar una confirmación posterior. Hacer commit de la toma sin registrar
una publicación no deja un lease permanente: la siguiente transacción puede
retomar el trabajo pendiente. Si la publicación o el commit es incierto, se
conservan ID y cuerpo. El receptor debe confirmar solo después de su propio
commit e impedir duplicación de efectos.

Fallar la publicación guarda backoff exponencial de uno a 64 segundos. Se limita
la demora, no el número de reintentos. Son tiempos técnicos de transporte, no un
SLA de atención ni una duración de sanción. Los errores Go son constantes sin
diagnósticos privados; backlog expone conteo/edad sin IDs ni contenido.

La marca de confirmación describe aceptación informada por el adapter del
broker. No significa que user aplicó el efecto ni que el usuario recibió un
aviso. El estado operativo no sustituye evidencia, auditoría de decisiones ni
anclaje independiente.

## Ensayos y fuente reproducible

`make test-ts-effect-relay` crea PostgreSQL desechable y ejecuta Go race/vet con
un publisher falso. Prueba orden por principal, progreso independiente, backoff,
ID/cuerpo exactos, aislamiento de funciones, toma abandonada, cancelación después
de una publicación simulada e inmutabilidad. No demuestra publisher confirms de
RabbitMQ. `ts_effect_relay_fixture.py` añade el protocolo y permisos a fresh,
upgrade no superusuario y restore de la suite general.

Los Go sources se transmiten desde Git al contenedor Linux. El SHA debe coincidir
con el manifiesto de compañeros y el checkout debe estar limpio. Los snapshots
guardan los tar originales y checksums; el lector rechaza otra revisión o un tar
alterado. Esto evita copiar `.git`/archivos sin seguimiento y no es un testigo
criptográfico independiente del PC.

La comprobación previa encontró admin en `rac-platform v0.18.0` y otros cuatro
consumidores en `v0.16.1`. Se regeneraron con herramientas Go normales desde el
módulo inmutable v0.18.0 ya publicado; no se movió ninguna etiqueta. Los dos
manifiestos fijan los nuevos commits y `check_go_vendor.py` vuelve a comparar
las reglas generadas con el checkout fijado de la plataforma.

Antes de publicar el lote deben estar accesibles los commits compañeros; una
configuración de CI preparada no implica que refs todavía locales se puedan
descargar ni que se haya ejecutado la CI remota.

### Evidencia local — 6 de noviembre de 2026

El primer ensayo del núcleo (`.local/p11-ts-relay-core-2026-11-06.log`) falló al
compilar: el nuevo import de `staff/postgres` no estaba en vendor. Se regeneró
desde el v0.18.0 ya fijado, sin cambiar la versión ni editar a mano el código
generado. El reintento terminó exit 0 en
`.local/p11-ts-relay-core-retry-2026-11-06.log`.

El primer snapshot `rac-p11-relay-proof-0eb098097ecb` terminó en el gate de
workflows: actionlint esperaba encontrar `.git`, ausente por diseño en la
exportación. Make ahora proporciona todos los archivos yml/yaml explícitamente;
no se deshabilitó la validación ni se fabricó un repositorio Git en la copia.
Ese fallo se conserva y no se cuenta como prueba verde.

La validación amplia está en
`.local/rac-p11-relay-proof-ec1c76e1e0c8/results.json`, todos sus 16 gates exit 0:
sintaxis, integridad de vendor, workflows, núcleo relay, permisos, migraciones
completas user/match/chat, EvidenceStore/casos HTTP reales en PG/RustFS, escaneo
y Go race de platform/auth/user/match/chat/alert/admin/payment. `revisions.json`
identifica cada fuente; payment se incluyó como checkout opcional limpio, sin
añadirle acceso al GitHub App ni cambiar sus fuentes. La revisión infra de esta
base es `9d0c3049b49abc86a93f8b3580b2a655eac41717`, admin `ab63edb`.

Después se agregó serialización del emisor entre casos antes del commit. La
prueba final de ese cambio está en
`.local/rac-p11-relay-order-proof-252eda92df2f/results.json`, cinco gates exit 0:
sintaxis, vendor, Go relay/race/vet, permisos con migrador no superusuario y
EvidenceStore/casos HTTP. Sus revisiones exactas son infra
`629eeb14e97bed828aaf1d8455fc20ea3c7a796e` y admin
`87cca3b91ac3754245c23dde802ebfe790309faf`. La producción Go del relay no cambió
entre esas revisiones de admin; se añadió la prueba de dos productores. Esta
prueba exige observar el segundo productor esperando el lock de principal,
ausencia de trabajo visible antes del primer commit y publicación ordenada
después de ambos commits. No se atribuye a la primera base una prueba que aún
no contenía ese cambio SQL.

El escaneo no encontró avisos alcanzables. Reportó avisos de módulos sin una
ruta de llamada actual; no se ocultaron ni equivale a afirmar que todas las
dependencias estén libres de avisos. El detalle del análisis queda en
`go-security.log` de la base amplia; P15 debe revalidarlo al integrar nuevas rutas.

También pasaron las pruebas de archivos congelados y el laboratorio SQL
focalizado (`.local/p11-relay-sql-2026-11-06.log`). No se aplicaron migraciones
al DEV habitual, no se ejecutó CI remoto y no hubo push. Los ensayos del relay
usan publisher falso: estos resultados no acreditan publisher confirms, consumo
o entrega de avisos en un broker real.

## Prueba con broker real — 7 de noviembre de 2026

`scripts/test_ts_relay_broker.py` levanta un RabbitMQ 4.3.6 desechable (sin
puertos publicados ni volúmenes existentes), declara `rac.trust_safety` y una
cuenta `relay` limitada a escribir ese exchange con la ruta
`ts.action.effective.v1`. Contra admin `29e41c77351a74c40b7b1f50dae3703f26ac3af1`
pasaron `TestRabbitConfiguration`, `TestRabbitHandshakeCancellation` y
`TestRabbitRealBroker`: cola quorum, rechazo `mandatory` sin ruta, mensajes
persistentes confirmados, identidad estable de duplicados y cancelación acotada
del handshake. Registro `.local/p11-ts-relay-broker-2026-11-07.log`, exit 0.

El primer intento falló con exit 1 y sin salida. `git archive` en Windows
aplicaba `core.autocrlf` y el gate de gofmt veía CRLF. `committed_sources.archive`
exporta ahora los bytes confirmados (`core.autocrlf=false`); no se desactivó el
gate. Esto no prueba la topología productiva, el worker ni el consumidor.

## Transporte completo — 7 de noviembre de 2026

- Admin `cmd/ts-relay` (rama `feat/ts-relay-worker`, 6aa0dee): worker opt-in
  (`TS_RELAY_ENABLED=true`, solo dev/test), credenciales únicamente desde
  archivos montados, backoff y logs de líneas fijas con conteo de backlog.
  La imagen incluye el binario; el entrypoint por defecto sigue siendo el
  servidor HTTP.
- User `cmd/ts-effects` e `internal/tseffects` (rama `feat/ts-effects-consumer`,
  11594fe): consumidor opt-in con login solo de funciones, verificado por
  `CheckRole`. Valida el sobre antes de la base de datos y hace commit antes
  del ack. Reencola los errores transitorios (40001, conexión) y envía a
  dead-letter los inválidos, conflictivos y los principales desconocidos.
- `configure_messaging.py` con `RAC_TS_MESSAGING=1`: exchange
  `rac.trust_safety`, cola quorum `rac.user.ts_effects` con dead lettering at
  least once, y roles `ts-publisher` y `ts-user` acotados. Sin el flag no se
  crea nada; `test_messaging_topology.py` prueba ambos casos.
- `scripts/test_ts_effect_e2e.py`: acción del caso → `ts.outbox` → worker
  relay → RabbitMQ (topología real) → consumidor → standing. La cuenta queda
  `restricted` (publish_listing) y vuelve a `active` tras revocar. No quedan
  entregas pendientes, la cola de fallidos queda vacía y no hay sujetos ni
  credenciales en los logs. Registro
  `.local/p11-ts-effect-e2e-2026-11-07.log`, exit 0.

## Pendiente antes de integrar

- Pruebas de fallo del broker durante la publicación (caída y reconexión) con el
  worker real; el adapter ya pasó la prueba básica con broker real.
- Topología quorum, dead lettering al menos una vez y cuentas de publicación y
  consumo con scopes mínimos. Provisión e incorporación al stack solo opt-in.
- Proceso worker, healthchecks, métricas sin PII y ensayo de reinicio/recuperación.
- Consumidor user con ready mínimo V058, commit antes de ack, clasificación de
  errores, reconexión y efectos correspondientes por tipo; `hide_listing` aún
  requiere aplicación por el dueño de publicaciones.
- Confirmación de aplicación por el dueño y estado visible de enforcement
  separado de la decisión/publicación. No anunciar una sanción aplicada ni un
  aviso recibido basándose solo en una decisión en cola o `confirmed_at`.
- Recovery/replay controlado desde eventos originales si se pierde el estado del
  broker; restauración/retenciones conforme al plan. No resetear confirmaciones
  ni regenerar IDs para ocultar trabajo pendiente.
