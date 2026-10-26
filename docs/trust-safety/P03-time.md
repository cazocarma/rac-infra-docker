# P03 — Reloj de autoridad y restricciones temporales

rac-platform v0.8.0 corrige una diferencia entre el reloj de la BD y el de los
servicios. Antes se evaluaban fechas de restricciones con `time.Now()` del
consumidor. Una instancia atrasada podía posponer el comienzo de una restricción;
una adelantada podía considerar que ya había vencido. El límite de dos segundos
del lease no corregía un desfase permanente entre relojes.

## Contrato y evaluación

La consulta PostgreSQL devuelve `observed_at = statement_timestamp()` junto con
estado, versión y restricciones, en una sola sentencia. No usa `now()` de una
transacción que pudiera haber empezado antes. El adaptador exige una fecha válida
y coherente entre filas. El transporte interno conserva esa fecha y rechaza
respuestas antiguas que no la incluyen. No se añade al contrato de eventos ni se
expone en la respuesta pública de estado de cuenta.

Sean S el inicio local de la consulta, R su recepción, A la hora devuelta por la
autoridad y N el momento local de evaluar. El tiempo actual de autoridad se trata
conservadoramente como el intervalo `[A + (N − R), A + (N − S)]`. Las diferencias
usan el componente monotónico de Go cuando las fechas provienen de `time.Now()`.
Así el desfase UTC del consumidor no cambia la decisión.

Una capacidad comercial se permite solo si ninguna restricción se solapa con ese
intervalo. El inicio es inclusivo y el final exclusivo. La incertidumbre puede
anticipar una denegación o retrasar una apertura hasta el RTT, pero no prolongar
permisos. La autorización vence dos segundos después de S; no se renueva al
consultar versión ni por un heartbeat. Evaluar antes de R, después de vencer o
sin fecha de autoridad deniega. Los derechos protectores de D02 se conservan.

El endpoint público `/me/standing` usa el mismo lease para sus indicaciones de
capacidades; no reintroduce el reloj local por ser una respuesta informativa.
Los escritores siguen comprobando autorización y versión antes del commit.
Una versión autoritativa regresiva también falla cerrada.

## Supuestos y límites

El origen autenticado debe muestrear fecha y datos durante la petición y no
devolver snapshots de caché. La BD es el reloj de referencia del dominio. Se
debe mantener y observar su sincronización; esta corrección no promete tolerar
saltos arbitrarios del reloj de la propia autoridad durante un lease. Tampoco
convierte la última comprobación y un commit en dos servicios en una transacción
distribuida. Siguen siendo necesarias la reconciliación y las mediciones E2E.

## Compatibilidad y evidencia

La prueba de regresión falló con el evaluador anterior para un desfase de −24 h.
Las pruebas de v0.8 cubren ±24 h, intervalo de incertidumbre, límites exactos,
vencimiento sin evento nuevo, dato temporal ausente, evaluación anterior a la
recepción, datos mutables y derechos protectores. También se prueba el recorrido
HTTP real con ambos desfases, la lectura PostgreSQL y la regresión de versión.

Esta versión requiere rollout coordinado: los lectores anteriores rechazan campos
JSON desconocidos y los nuevos rechazan snapshots sin `observed_at`. Detener las
escrituras, desplegar autoridad y lectores fijados y comprobarlos antes de
reabrir tráfico. No hay migración de datos para este campo calculado. No mezclar
revisiones ni usar una respuesta sin fecha como fallback permisivo.

Estos resultados son funcionales. No acreditan por sí solos el SLO p99 de cinco
segundos ni el presupuesto de latencia de dos milisegundos.
