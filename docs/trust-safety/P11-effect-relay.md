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

## Pendiente antes de integrar

- Adapter real con mensajes persistentes, `mandatory`, confirmación positiva y
  cierre de socket por cancelación; prueba con RabbitMQ real y fallos.
- Topología quorum, dead lettering al menos una vez y cuentas de publicación y
  consumo con scopes mínimos. Provisión e incorporación al stack solo opt-in.
- Proceso worker, healthchecks, métricas sin PII y ensayo de reinicio/recuperación.
- Consumidor user con ready mínimo V058, commit antes de ack, clasificación de
  errores, reconexión y efectos correspondientes por tipo; `hide_listing` aún
  requiere aplicación por el dueño de publicaciones.
- Recovery/replay controlado desde eventos originales si se pierde el estado del
  broker; restauración/retenciones conforme al plan. No resetear confirmaciones
  ni regenerar IDs para ocultar trabajo pendiente.
