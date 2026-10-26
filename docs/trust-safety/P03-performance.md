# P03 — Caché de autorización y medición reproducible

## Implementación

Platform v0.9.1 incorpora una caché LRU limitada a 1024 sujetos, compartida por
instancia. Guarda el lease original, con su vencimiento original de como máximo
dos segundos. Solo lo reutiliza cuando conserva al menos un segundo. Las cargas
concurrentes del mismo sujeto se agrupan; los esperadores pueden cancelar.

Una versión más nueva, regresiva o una consulta de versión fallida invalida la
entrada. Las cargas antiguas en curso no pueden repoblarla después de una
invalidación o expulsión. Un permiso negativo se refresca antes de decidir,
para que levantar una restricción no espere el TTL. Las operaciones con varias
partes conservan el vencimiento más temprano, sin renovar el presupuesto.

La caché acelera Acquire, pero Check consulta nuevamente la versión autoritativa
antes del commit. User comprueba también antes de subir la foto o provisionar el
rol compa. El alta inicial consulta su baseline dentro de la transacción, sin
cachear datos no confirmados. La recuperación histórica usa el cliente fresco.

Los histogramas del SDK no contienen identificadores ni contenido de usuarios.
Las respuestas Prometheus que combinan registro y SDK desactivan compresión para
no concatenar datos sin comprimir a un flujo gzip; hay una regresión específica
que ofrece gzip y comprueba ambas familias de métricas.

## Ensayo local del 25-10-2026

[Evidencia JSON](evidence/p03-performance-v091.json), con revisiones inmutables,
hash del harness, hardware y estado final. Docker 29.8.2, 12 CPU y aproximadamente
7.73 GiB de memoria. Ejecutar desde la raíz de RAC:

```powershell
python rac-infra-docker/scripts/test_standing_e2e.py --measure --report .local/p03-performance.json
```

El runner exige companions limpios y fijados en el manifiesto, verifica vendor,
crea un proyecto Compose aleatorio sin puertos ni volúmenes del DEV y elimina
solo sus recursos. No utiliza credenciales ni sesiones personales. El informe
empieza como running y solo termina complete después de todas las fases.

Se confirmaron 100 sanciones reales con seis sondas concurrentes: perfil,
disponibilidad y mensaje, dos instancias por servicio. Cada ensayo verifica
primero una escritura permitida y conserva los JWT reales emitidos antes de las
sanciones. La carga objetivo es diez peticiones por segundo por sonda, en bucle
cerrado; el informe conserva overruns y reintentos de restauración. No descarta
5xx, timeouts ni sondas ausentes para mejorar percentiles.

El commit se encierra entre dos lecturas monotónicas y se usa el extremo más
temprano: la cota hasta completar la última respuesta exitosa es conservadora
respecto del momento real del commit SQL. El primer rechazo incluye resolución
de sondeo de 100 ms; no equivale al instante exacto de revocación.

| Ruta / instancia | Primer rechazo p99 ms | Último éxito posterior al commit, cota p99 ms | Acquire hit observados | Hit <=2 ms | HTTP caliente p99 ms |
|---|---:|---:|---:|---:|---:|
| user.profile / 1 | 93.980 | 0.000 | 198 | 198 | 26.712 |
| user.profile / 2 | 92.822 | 0.000 | 199 | 199 | 28.432 |
| match.availability / 1 | 96.953 | 0.701 | 198 | 198 | 31.472 |
| match.availability / 2 | 97.520 | 0.000 | 198 | 198 | 23.074 |
| chat.send / 1 | 101.652 | 2.933 | 197 | 197 | 37.686 |
| chat.send / 2 | 101.211 | 2.608 | 197 | 197 | 37.032 |

La fase caliente ejecutó 200 peticiones por sonda, seis sondas concurrentes.
El gate exige al menos 100 hit nuevos por instancia y 99% dentro del bucket
<=2 ms del histograma real de Acquire. No interpola un percentil dentro de un
bucket y no sustituye Acquire por un benchmark del evaluador puro. La consulta
fresca de commit y la petición HTTP completa tienen un coste adicional.

También pasó la matriz funcional completa: todos los escritores contemplados,
seis carreras de commit con rollback, caída/reinicio del broker y autoridad,
recuperación y conservación de accesos protectores. La fase estadística cubre
tres rutas representativas; no certifica todos los endpoints bajo cualquier
carga ni un SLO de producción. El baseline sin caché está conservado en
[evidencia anterior](evidence/p03-revocation-baseline.json); el harness evolucionó,
por lo que no se presenta como una comparación controlada de velocidad.

## Observación continua

Grafana provisiona el dashboard `RAC · Autorización de cuenta`, con seis paneles:
proporción de Acquire hit dentro de 2 ms, volumen hit/miss, p99 de refresh, p99 de
Check fresco, tamaño de muestra y HTTP completo. Todos distinguen instancia.
Los cuantiles operacionales de histogramas se interpolan; el gate de 2 ms usa
la proporción exacta del bucket, igual que el ensayo.

La alerta `RACStandingHotAcquireBudgetExceeded` exige menos de 99% dentro de
2 ms, al menos 100 hit en diez minutos y cinco minutos de incumplimiento.
No agrega instancias entre sí: una instancia sana con mucho tráfico no oculta
a otra lenta. promtool prueba incumplimiento sostenido, frontera exacta de 99%,
muestra insuficiente, tráfico cold, inactividad y reinicio de contadores. Las
17 reglas y esos escenarios pasan; CI ejecuta las pruebas de la alerta.

## Medición final del 26-10-2026

La [evidencia final](evidence/p03-final-performance.json) agrega `match.accept`
en dos instancias: ocho sondas concurrentes, 100 sanciones auditadas, JWT reales
anteriores y la misma cota conservadora desde el commit. Cada aceptación usa
una reserva nueva pendiente y comprueba la transición real a activa. La
preparación SQL del fixture ocurre fuera del tiempo HTTP; un entitlement
sintético, solo dentro del laboratorio, evita confundir el límite gratuito con
una denegación de standing. Los horarios no cruzan medianoche.

El peor p99 de primer rechazo fue **93.273 ms**; para aceptación, **22.271 ms**
y **20.229 ms**. La cota p99 del último éxito posterior al commit fue 0 ms en
esta muestra; esto no promete ausencia universal de carreras ni latencia cero.
Los 1184 hits calientes estuvieron dentro del bucket de 2 ms. La fase caliente
mantiene seis sondas; no se atribuye ese histograma a rutas individuales.

La carga de aceptaciones expuso una pausa fija por evento en el relay. Se
retiró la pausa después de publicaciones confirmadas; se conservan espera idle,
backoff de error, confirmaciones, orden por agregado y comprobación de apagado.
La matriz posterior completó publicación y vaciado de colas con el plazo
original, sin aumentarlo para hacer pasar el ensayo.

## CI y activación

El job integrado ejecuta el mismo gate y publica únicamente el JSON saneado
como artefacto durante siete días, incluso ante fallo. Un resultado local no
reemplaza el check remoto de las revisiones finales.

Las sesiones y el respaldo/restore del DEV ya tienen evidencia en
[P03-sessions](P03-sessions.md) y [cierre](P03-close.md). El check remoto debe
corresponder a la revisión final. La activación persistente es una operación
coordinada, no un efecto implícito de obtener un percentil favorable.
