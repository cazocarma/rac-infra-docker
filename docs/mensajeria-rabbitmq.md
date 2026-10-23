# Reservas, outbox y RabbitMQ

Implementación del 21 de octubre de 2026. El flujo es:

`transacción de reserva + booking_outbox → events-relay → RabbitMQ → consumer → inbox + notificaciones`

## Propiedad y garantías

V013 reemplaza atómicamente el productor de V005. No modifica las migraciones ya
aplicadas ni regenera avisos históricos. Los IDs y fechas de lectura existentes se
conservan. El trigger genera un evento solo al crear una reserva o cambiar realmente
su estado; asigna una revisión creciente por reserva en esa misma transacción.
Una operación revertida no deja evento. Se retiraron la conexión/publicación
AMQP legacy de los handlers, sus errores descartados y la configuración antigua
`RABBITMQ_URL`/`RABBIT_EXCHANGE`. HTTP no hace doble escritura ni abre conexión
al broker durante el arranque.

Match contiene el relay como ejecutable separado en su misma imagen. Cada publicación
usa mensaje persistente, `mandatory` y publisher confirms. Solo después del confirm,
sin retorno por falta de ruta, marca `published_at`. Un timeout, nack o resultado
incierto conserva la misma ID para reintentar. PostgreSQL coordina relays concurrentes
con `FOR UPDATE SKIP LOCKED`; una revisión posterior no adelanta una pendiente de
la misma reserva, incluso si esta espera su próximo intento. Las demás reservas
pueden continuar. El lock dura como máximo el timeout de la operación, no una espera
indefinida del broker. El backoff de publicación crece hasta 64 segundos.

Alertas contiene un consumidor separado con ACK manual y prefetch 1. Valida el
contrato, guarda el marcador único de inbox y los avisos en una transacción y confirma
al broker después del commit. Una caída entre commit y ACK produce reentrega, pero
no repite efectos ni borra marcas de leído. La revisión ordena la publicación; no
promete orden global de procesamiento con múltiples consumidores. Los avisos conservan
la fecha del evento. Reservas o identidades eliminadas no se recrean por entrega tardía.

La entrega es **al menos una vez**, con efectos idempotentes. Los confirms y los ACK
son garantías diferentes: [documentación oficial](https://www.rabbitmq.com/docs/confirms).
La BD aún es compartida y usa las credenciales existentes: la separación de permisos
PostgreSQL por servicio sigue pendiente antes de PRD.

## Broker y permisos

RabbitMQ 4.3.6 management está fijado por digest, como parche soportado de la serie
4.3. No se reutiliza el directorio de datos de 3.13: `rabbitmq-events-data` es nuevo;
el volumen histórico `rabbitmq-data` queda conservado. El broker anterior fue
verificado sin colas antes del cambio local. No hacer este cambio sobre otro entorno
sin inventario de sus mensajes y procedimiento de migración.

Al adoptar el volumen nuevo desde un DEV antiguo, cambiar `RABBITMQ_USER` de
`guest` a `rac-operator` y generar una contraseña local en el archivo ignorado.
Guest solo admite loopback y no sirve para el inicializador por red; no se desactiva
esa protección. Las plantillas DEV ya usan el administrador con nombre propio.

El hostname del nodo es estable. Los healthchecks y las sondas del test ejecutan
`rabbitmq-diagnostics` como el usuario rabbitmq: ejecutarlo como root al primer
arranque puede crear la cookie de Erlang con propietario incorrecto.

`messaging-config` configura de forma idempotente el vhost `rac-dev`, `rac-qa` o
`rac-prd`, exchanges, colas quorum, bindings y política. Es el único proceso que
recibe el administrador del broker. Genera credenciales aleatorias separadas:

- Publisher: escribir únicamente en `rac.bookings`.
- Consumer: leer únicamente `rac.alert.bookings`.
- Ninguno puede configurar topología ni acceder a otro vhost.

Las URLs se guardan en dos volúmenes distintos montados de solo lectura en cada
worker. Nunca se registran ni se pasan al navegador. La consola y AMQP solo se
publican sobre loopback en DEV; QA/PRD no publican esos puertos. Las APIs de reservas
y bandeja no dependen del estado del broker. Los workers requieren la configuración
inicial, y se reconectan con backoff y jitter tras interrupciones.

## Topología y fallos

Exchange topic durable `rac.bookings`; routing key `booking.state_changed.v1`;
cola quorum `rac.alert.bookings`. Otros futuros consumidores necesitan colas propias.
El contrato ejecutable está en `rac-shared-contracts/events`; solo contiene UUIDs,
estado, revisión y fecha. No contiene correos, nombres, tokens ni conversaciones.

Los contratos inválidos y las colisiones de ID con distinto cuerpo se guardan en
`alert_event_quarantine` antes del ACK. Se limita el cuerpo guardado a 16 KiB, con
hash del original y razón controlada. No se imprimen cuerpos en logs. El acceso a
esa tabla es operativo y restringido; no se expone en la API de usuarios.

Los errores de persistencia cierran la conexión sin ACK y esperan con backoff.
Después de 20 entregas fallidas, la política quorum remite el mensaje al exchange
`rac.bookings.failed`, routing key `failed`, cola `rac.alert.bookings.failed`.
Usa `dead-letter-strategy=at-least-once` y `overflow=reject-publish` para evitar la
pérdida del DLX por defecto. Véase [quorum queues](https://www.rabbitmq.com/docs/4.3/quorum-queues).
No se purgan ni reproducen automáticamente mensajes fallidos.

## Operación y recuperación

Desde infra: `make up`, `make ps` y `make check`.
`make check` valida también la readiness de ambos workers, de modo que el gate de
promoción requiere las imágenes coordinadas con sus ejecutables y un consumidor
conectado, además de las APIs HTTP.
La prueba aislada es `python scripts/test_messaging.py`. Crea PostgreSQL y RabbitMQ con nombres aleatorios,
no lee archivos .env y elimina solo sus recursos al terminar. Se ejecuta también en
CI integrado usando los SHAs fijados de match y alertas.

Prometheus recoge broker y workers. Grafana provisiona el dashboard `RAC · Mensajería`
con salud, backlog, antigüedad, colas, procesamiento, deduplicación y fallos. Se observan cantidad/edad de outbox pendiente,
publicaciones, errores, reentregas deduplicadas, cuarentena, conexión y profundidad
de colas. Las reglas alertan por demora, desconexión y mensajes fallidos. IDs de
usuarios/eventos/reservas no son etiquetas. La readiness del consumidor exige conexión
y BD; la del relay verifica BD, mientras el backlog muestra bloqueos de publicación.

Ante cola de fallidos: corregir primero la causa y verificar consumer/BD. Un operador
puede recuperar un evento concreto desde el outbox canónico, conservando la ID:

```sql
BEGIN;
UPDATE booking_outbox SET published_at=NULL,next_attempt_at=now()
WHERE id = '<UUID verificado del evento>';
COMMIT;
```

Verificar el marcador de `alert_event_inbox` y los avisos esperados antes de retirar
esa entrega de la cola de fallidos. Una repetición ya procesada es inocua. No resetear
todo el outbox ni usar purge. La cuarentena requiere revisión del contrato/cuerpo;
no se debe reenviar ciegamente. La automatización de este procedimiento queda para
una herramienta operativa con auditoría y permisos propios.

Antes de revertir V013, detener ambos workers y drenar/verificar el outbox. Volver
solo a la imagen anterior dejaría eventos nuevos sin consumidor; no reactivar V005
mientras haya entregas pendientes. Las migraciones aplicadas se corrigen con una
migración nueva, nunca editando su checksum.

## Validación y límites

Las pruebas verifican preservación V012→V013, rollback sin evento, no-op sin evento,
orden por reserva, relays concurrentes, confirm perdido, mandatory sin ruta,
deduplicación concurrente, rollback del inbox, conflicto de ID, persistencia de
cuarentena, y conexión cortada después del commit y antes del ACK con broker real.
`python scripts/test_messaging_recovery.py` detiene solo el broker DEV, confirma
un cambio de reserva por HTTP con el broker caído y verifica su entrega única al
restaurarlo; usa un comprador OIDC desechable y restaura el broker en `finally`.
Las pruebas HTTP/navegador esperan el efecto asíncrono con un plazo acotado y fallan
inmediatamente ante errores HTTP.

DEV sigue teniendo un solo nodo: durabilidad no equivale a alta disponibilidad.
Antes de PRD faltan TLS del transporte, capacidad/replicación, retención de outbox,
inbox y cuarentena, rotación de credenciales y permisos PostgreSQL separados. Los
respaldos de BD incluyen el outbox/inbox; no incluyen el volumen del broker. La copia
fuera del PC continúa aplazada por decisión del usuario. Correo y push siguen pendientes.
