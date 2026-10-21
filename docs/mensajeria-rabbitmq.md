# Evaluación de RabbitMQ para RAC

Estado: propuesta de arquitectura; todavía no hay publicador ni consumidor AMQP en las aplicaciones. La instalación del contenedor no equivale a tener mensajería integrada.

## Decisión propuesta

Usar RabbitMQ para eventos de dominio asíncronos, empezando por cambios de reservas que alimenten alertas. Mantener HTTP para consultas y acciones que necesitan una respuesta inmediata. El chat actual conserva su outbox y recuperación por cursor; RabbitMQ no sustituye la autorización por reserva ni se expone al navegador.

Actualmente V005 genera los avisos dentro de la misma transacción que cambia la reserva. El nuevo servicio de alertas es dueño de su API de lectura y marcado, pero PostgreSQL sigue compartido y el trigger sigue escribiendo la bandeja. Esta es una transición explícita, no una separación completa de datos por microservicio.

## Flujo objetivo y garantías

1. Match guarda reserva y evento outbox en una transacción PostgreSQL. Evento inmutable con `event_id` UUID, `event_type`, versión del contrato, `booking_id`, revisión del agregado, instante y destinatarios mínimos. Sin JWT, correo, teléfono, descripción del incidente ni mensajes privados.
2. Un relay publica el evento persistente en un exchange durable de tipo topic, con `mandatory` y publisher confirms. Solo marca el outbox como publicado cuando hay confirmación y no hubo retorno por ausencia de ruta. Un cierre o timeout deja el evento disponible para reintento; el relay se reconecta con backoff limitado y jitter.
3. Una cola durable exclusiva del consumidor de alertas recibe los tipos de evento que necesita. El consumidor guarda `event_id` procesado y las notificaciones en una única transacción. Una restricción única impide duplicados incluso con consumidores concurrentes. Solo entonces envía ACK manual; si el proceso cae entre commit y ACK, la reentrega no repite el efecto.
4. Los fallos transitorios tienen reintentos demorados y acotados. Los contratos inválidos y los eventos que agotan los intentos pasan a una cola de fallos, con diagnóstico sin datos privados. No usar requeue infinito ni ACK antes de persistir.

La entrega es al menos una vez; no se promete exactly-once entre PostgreSQL y RabbitMQ. Los duplicados y las interrupciones son parte normal del modelo. Los confirms del publicador y los ACK del consumidor son garantías distintas. Fuentes: [Reliability Guide](https://www.rabbitmq.com/docs/reliability) y [Consumer Acknowledgements and Publisher Confirms](https://www.rabbitmq.com/docs/confirms).

## Topología y operación

Propuesta de nombres versionados: exchange `rac.domain.v1`, routing key `booking.state_changed.v1`, cola `rac.alert.booking.v1` y cola de fallos `rac.alert.booking.failed.v1`. Otros consumidores tendrán sus propias colas, no competirán por la de alertas. Los contratos se versionarán en rac-shared-contracts antes de publicar.

Separar usuario/vhost del broker por ambiente y permisos de publicar/consumir por servicio. Las credenciales no van al frontend ni al repositorio. Fijar una versión soportada y digest al implementar; no reutilizar sin revisión la etiqueta histórica `rabbitmq:3-management`. La consola queda restringida al entorno local. Fuera de DEV harán falta TLS, límites, métricas y una decisión explícita de disponibilidad/replicación. Un único contenedor con volumen no ofrece alta disponibilidad.

Medir cantidad/edad del outbox pendiente, retornos/nacks, reconexiones, profundidad de cola, mensajes sin ACK, reintentos y cola de fallos. No usar IDs de usuario/reserva como etiquetas de métricas. Definir retención y procedimiento de replay; los respaldos actuales no incluyen las colas de RabbitMQ.

## Transición verificable

No reemplazar V005 con un envío directo desde el handler: introduciría el problema de doble escritura. En una migración coordinada, pasar del trigger de notificaciones al outbox de reservas. Solo un camino debe crear cada aviso; para conservar avisos existentes sin duplicados, el corte requiere contrato de identidad, prueba de migración y revisión de los datos históricos. Las migraciones V001–V012 aplicadas no se reescriben.

Antes de activar el consumidor: probar caída del broker durante una reserva, publicador reiniciado antes/después del confirm, consumidor reiniciado antes/después del commit, duplicados concurrentes, mensaje sin ruta, contrato inválido, agotamiento de reintentos, orden/revisión del agregado y replay desde la cola de fallos. La reserva debe persistir durante la caída y el aviso llegar al recuperarse sin duplicar efectos.

Primero se entrega la bandeja privada y sus pruebas. La implementación de este flujo AMQP es el siguiente incremento independiente, para ensayar recuperación sin mezclarla con el cambio de propietario de la API.
