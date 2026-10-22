# ADR-001 — Standing autoritativo y propagación

Estado: dirección técnica D01 aprobada; matriz D02 pendiente en [plan](plan.md).

## Problema

Roles Keycloak y JWT válidos no expresan una suspensión reciente. Consultar solo el JWT permite continuar hasta su vencimiento. Duplicar reglas en servicios hace divergentes las decisiones. Un evento asíncrono tampoco garantiza por sí solo el límite de cinco segundos.

## Propuesta

`rac-user-service` será autoridad de `account_standing` y `account_restrictions`, con FK al `usuario` real, no a la tabla ilustrativa `users` del prompt. Estados active/restricted/suspended/banned; versión monotónica por usuario y restricciones por capacidad/intervalo. `rac-platform/standing` contiene tipos y evaluación común; cada servicio mantiene su adaptador y autorización de propiedad.

Capacidades iniciales del prompt: publish_listing, request_booking, accept_booking, send_message, write_review, submit_report, appeal. La matriz deberá agregar explícitamente los flujos de seguridad, cancelación, privacidad, aceptación de documentos y recuperación que no caben en ese enum. No se aplicará un bloqueo genérico a todo POST: no puede impedir reportar, apelar, cerrar sesión ni ejercer derechos. D02 define las excepciones para banned y ventanas vencidas.

El cambio y `user.standing.changed.v1` se guardan en una transacción. Payload mínimo: event_id, subject_id, status, effective_capabilities, standing_version, policy_version, occurred_at y referencia opaca al caso; sin descripción privada. Cada dueño recibe todos los eventos en su propia cola, inbox y actualización atómica `incoming.version > stored.version`. Duplicados/desorden no restauran privilegios. Reconciliación periódica compara versiones con la autoridad.

Cache/proyección lleva frescura verificable de la autoridad. Propuesta: lease de frescura de hasta 2 s, invalidación inmediata por evento y refresh síncrono al faltar/vencer. Una lectura local o heartbeat del broker no renueva el lease. Si falla refresh, se niega escritura y se conserva lectura pública. El máximo de 10 s del prompt es un techo, no el TTL elegido. No se acepta una proyección de 10 s como prueba del objetivo de 5 s.

Comprobar actor y contrapartes según operación: reservar exige compa publicable/activo; aceptar y enviar no pueden ignorar que el otro participante fue suspendido. La decisión de autorización se liga a versión y caducidad y se vuelve a validar antes del commit. Operaciones largas y reintentos no reutilizan una autorización vencida. Los caminos críticos pueden requerir consulta síncrona; el contrato documentará el orden de commits y el presupuesto de latencia. No hay garantía absoluta de atomicidad entre BD distintas sin un protocolo adicional: se medirá el límite de exposición y se rechazará cualquier autorización stale, incluso durante una partición.

Suspensión/ban genera comandos idempotentes por dueño: ocultar publicaciones; cancelar reservas futuras pendientes/activas por enforcement; devolver cupo a la contraparte según D03; chat solo lectura; notificación neutral. Un evento antiguo no revierte una decisión más nueva. El estado autoritativo bloquea primero, aunque la limpieza derivada tarde. Revertir una sanción no resucita reservas vencidas/canceladas ni cobra nuevamente.

Keycloak mantiene login para aviso/apelación durante suspensión. Cerrar sesiones y tokens cortos son defensa complementaria; no sustituyen standing. Deshabilitar cuenta queda limitado al supuesto aprobado de ban definitivo fuera del plazo o compromiso, preservando los canales de derechos.

## Alternativas y consecuencias

JWT-only rechazado por revocación tardía. Consulta remota en toda escritura puede servir de referencia de seguridad, con coste de disponibilidad y latencia; proyección sola rechazada por lag sin límite. La solución elegida añade reconciliación y denegaciones durante fallos, aceptadas por fail-closed.

## Pruebas y gate

JWT anterior a suspensión en cada endpoint; dos participantes; carreras al commit; broker detenido; autoridad caída; entrega duplicada/invertida; reconciliación; reloj/lease vencido; expiración de restricciones sin nuevo evento. Medir desde commit autoritativo hasta última escritura autorizada: p99 ≤5 s y prohibición de autorizar con lease vencido; hot path p99 ≤2 ms en carga definida, excluyendo refresh pero midiendo también latencia total. No declarar cumplimiento con una única ejecución funcional.
