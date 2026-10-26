# P03 — Matriz de verificación y trabajo restante

Esta matriz distingue controles implementados de aceptación completa. No sustituye
[acceptance](acceptance.md), que abarca todo el programa Trust & Safety. El preview
sigue desactivado en el DEV persistente. V026/V027 y platform v0.9.1 requieren despliegue
coordinado y las revisiones inmutables del manifiesto integrado.

## Rutas existentes

| Dueño / escritura | Control comercial | Accesos que se conservan |
|---|---|---|
| User: `PUT /me`, `POST /profile` | `publish_listing` del actor, transacción y comprobación final; alta inicial consulta su baseline no confirmado en la misma transacción | Perfil propio y estado de cuenta autenticados |
| User: `PUT /me/compa`, `POST /compas`, `POST /compas/:id/skills` | `publish_listing`, actor y dueño cuando corresponde; no bypass por alias antiguo | Consulta propia y catálogo permitido |
| User: `PUT /me/photo` | Permiso antes de escribir y antes del commit; limpia objeto nuevo si se deniega | Lectura y borrado de foto propia |
| User: `POST /bookings/:id/review` | `write_review` de ambos participantes, propiedad y elegibilidad | Lectura de reseñas públicas autorizadas |
| Match: `POST /session` | `request_booking` del solicitante y `accept_booking` del compa; cupo y prueba de autorización atómicos | Consulta de reservas propias |
| Match: `PUT /session/:id/state` al aceptar | `accept_booking` del compa y `request_booking` de contraparte; admin no reemplaza consentimiento | Cancelación propia según reglas y propiedad |
| Match: `POST /session/:id/extend` | Permisos de participantes, reserva aún activa y comprobación final | Sin reapertura de canceladas |
| Match: agenda semanal y alta/borrado de time-off | `publish_listing` del actor y dueño, comprobación final y rollback | Lectura propia de agenda |
| Chat: `POST /bookings/:id/messages` | `send_message` de ambos, propiedad de reserva, autorización final e idempotencia | Historial, seguridad, bloqueo y reporte según propiedad/elegibilidad |
| Alert: marcar aviso individual/todos como leído | No es una acción comercial; no depende de standing | Solo bandeja propia, también durante sanción |

Las rutas se expresan relativas al prefijo `/api/<servicio>`. El dashboard de
admin es lectura; las rutas de moderación legacy conservan su control específico
y no adquieren permisos comerciales. La migración completa de staff/casos es P11.
Auth conserva el ingreso para informar y ejercer derechos. Payment no tiene un
flujo de cobro activo que pueda declararse cubierto por estas pruebas.

El catálogo, detalle, reseñas y fotos públicos consultan standing en la BD de su
dueño, antes de paginar. Los adaptadores remotos comerciales usan autoridad
autenticada; una proyección o un JWT viejo no otorgan por sí solos autorización.

## Evidencia ejecutable

| Control | Evidencia automatizada |
|---|---|
| Reglas, límites temporales y relojes | `rac-platform`: `go vet ./...`, `go test -race ./...`; leases con ±24 h de desfase, incertidumbre RTT, fecha ausente, expiración sin evento y versión regresiva |
| Reservas y protección | `scripts/test_migrations.py`: JWT firmado anterior a sanción en dos instancias, ambas partes, caída, espera de locks, rollback/cupo y cancelación protectora |
| Escritores de user/chat | Misma suite con PostgreSQL migrado y roles scoped: perfiles, onboarding, habilidades, reseñas, medios y envío; no todos usan JWT real en estos fixtures |
| Efectos D03 y recuperación | Historial original independiente del broker, sanción perdida seguida de reversión, lotes, claims vencidos y fencing; permisos nuevos sobreviven a sanción antigua |
| Avisos privados | `scripts/test_messaging.py` exige PASS de las cuatro suites de standing de alert; PostgreSQL/RabbitMQ reales, ACK perdido, permisos, lectura preservada, conflicto y descubrimiento sin reservas |
| Identidad de servicio | `scripts/test_identity_permissions.py`: Keycloak real, firma/OAuth, tres clientes mínimos sin administración y rutas limitadas por propósito |
| Separación de BD y restore | `scripts/test_database_permissions.py`: fresh/adopción, migrador sin superusuario, permisos negativos y backup/restore |
| Integridad de dependencia compartida | `scripts/check_go_vendor.py`, `scripts/test_go_vendor.py`: misma versión inmutable en cuatro consumidores y detección de edición manual |
| UX y contrato | Flutter analyze, 41 tests y build web; avisos a 360/1200 px, null sin reserva inventada, leído y navegación; OpenAPI y tests JSON |
| Configuración y observación | `scripts/check_configuration.py`: DEV/QA/PRD y overlay aislado; promtool: 17 reglas y escenarios de presupuesto caliente; `make check` incluye el nuevo worker |

Una suite Go sin variables de fixture puede saltar pruebas PostgreSQL: su éxito
no reemplaza los runners integrados. El CI debe evaluar los SHAs exactos fijados,
no inferir que un check verde anterior cubre cambios posteriores.

Verificación local del 24-10-2026: plataforma y cuatro servicios pasaron vet/race;
los runners completos de migraciones, mensajería e identidad pasaron con v0.8.0.
Flutter, contratos, configuración y promtool pasaron. La prueba de permisos/restore
de V026 pasó antes del ajuste de reloj, que no modifica migraciones ni grants.
El build Docker actualizado de alert también pasó. El estado remoto debe leerse
en los checks del PR para la revisión fijada en el manifiesto.

Verificación local del 25-10-2026: platform v0.9.1 y los cuatro consumidores
pasaron vet/race; el runner completo de migraciones pasó nuevamente con las
revisiones fijadas, incluidos perfiles y reseñas, rollback, fresh/adopción,
repetibilidad y rechazo de drift. La matriz Compose completa y los dos gates
estadísticos pasaron. Promtool valida 17 reglas y los escenarios de la nueva
alerta. Los resultados anteriores de identidad y Flutter corresponden a su
revisión indicada; no se modificaron esas integraciones en esta entrega.

El [CI 40246956163](https://github.com/cazocarma/rac-infra-docker/actions/runs/40246956163)
pasó sus cuatro trabajos en la revisión `449d5bb`: storage, accesos, migraciones
e integración, incluida la matriz Compose con ambos gates estadísticos y el
recorrido en navegador. Publicó el artefacto de rendimiento saneado. Esto prueba
esa revisión; no sustituye el CI del adaptador de sesiones ni del futuro worker.

## Estado de gates al 26-10-2026

1. La matriz Compose completa pasa con el efecto de sesiones integrado,
   caída de Keycloak, reinicio del worker, JWT anterior y derechos protectores.
2. La medición final incluye aceptación real de reservas en dos instancias:
   100 sanciones, ocho sondas y peor p99 de primer rechazo 93.273 ms.
3. El gate caliente pasa con 1184/1184 hits <=2 ms. HTTP, consulta fresca y
   adquisición con caché se distinguen; ver metodología y límites.
4. El CI de `0583dfd` pasó sus cuatro jobs. Falta el CI de esta revisión final
   con la ampliación de medición y el relay sin pausa por evento confirmado.
5. El DEV real tiene cold backup cifrado/restaurado y backup lógico restaurado.
   La copia restaurada pasa V017→V027, validate, repetición y conteos preservados.
6. V027 y el worker mínimo de sesiones pasan carreras, ACK perdido, claims,
   reversión, permisos y revocación online/offline real. El cierre de sesiones
   no sustituye la autoridad de capacidades ni bloquea el ingreso protector.

El [expediente de cierre](P03-close.md) enlaza la evidencia de cada requisito,
el alcance aprobado y la siguiente entrega P04. El rollout persistente sigue
separado del cierre de código; no se activa por inferencia de una prueba.

La revisión del código oficial de [Keycloak 26.8.1, UserResource](https://github.com/keycloak/keycloak/blob/26.8.1/services/src/main/java/org/keycloak/services/resources/admin/UserResource.java)
confirma que `logout()`, modificar y borrar usuarios exigen el mismo control
`requireManage(user)`. Por eso un grant de gestión no equivale a una identidad
limitada a cerrar sesiones. El nuevo adaptador usa el SPI REST y proveedores de
sesiones, sin tablas JPA propias ni credenciales de administración. No se declara
conectado al cambio de standing solo por tener ese endpoint.
La recuperación de un evento antiguo tampoco debe cerrar sesiones nuevas después
de una reversión. El principal técnico actual conserva su alcance previo.

Los avisos jurídicos completos, casos, apelaciones y atribución de decisiones
humanas pertenecen a P11; documentos a P04, identidad baneada a P05 y privacidad
completa a P12. No se presentan como funciones existentes. La cuenta técnica
actual que asigna `compa` no recibe administración general para cerrar sesiones:
ese efecto requiere un mecanismo acotado y pruebas antes de activarse. El control
de standing no depende de que Keycloak cierre una sesión.
