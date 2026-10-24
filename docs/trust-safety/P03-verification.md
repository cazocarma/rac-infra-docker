# P03 — Matriz de verificación y trabajo restante

Esta matriz distingue controles implementados de aceptación completa. No sustituye
[acceptance](acceptance.md), que abarca todo el programa Trust & Safety. El preview
sigue desactivado en el DEV persistente. V026 y platform v0.8.0 requieren despliegue
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
| Configuración y observación | `scripts/check_configuration.py`: DEV/QA/PRD y overlay aislado; promtool: 16 reglas; `make check` incluye el nuevo worker |

Una suite Go sin variables de fixture puede saltar pruebas PostgreSQL: su éxito
no reemplaza los runners integrados. El CI debe evaluar los SHAs exactos fijados,
no inferir que un check verde anterior cubre cambios posteriores.

Verificación local del 24-10-2026: plataforma y cuatro servicios pasaron vet/race;
los runners completos de migraciones, mensajería e identidad pasaron con v0.8.0.
Flutter, contratos, configuración y promtool pasaron. La prueba de permisos/restore
de V026 pasó antes del ajuste de reloj, que no modifica migraciones ni grants.
El build Docker actualizado de alert también pasó. El estado remoto debe leerse
en los checks del PR para la revisión fijada en el manifiesto.

## Gates todavía abiertos

1. El [ensayo Compose](P03-compose.md) pasó localmente: JWT real previo, dos
   instancias de user/match/chat, escritores, seis carreras de commit, caída de
   broker/autoridad, reinicio, recuperación y derechos protectores. Falta confirmar
   su ejecución en CI para la revisión final.
2. Medición reproducible desde commit de sanción hasta última escritura admitida:
   p99 ≤5 s, con muestra, concurrencia, hardware y fallos documentados. No hay
   todavía un resultado que permita afirmar ese SLO.
3. Presupuesto de autorización caliente p99 ≤2 ms y latencia total separados.
   Los caminos actuales privilegian consulta fresca; no existe una caché caliente
   cuya eficacia pueda deducirse de un benchmark del evaluador puro.
4. Cierre de revisión por requisito y CI remoto de la revisión final. Mantener PR
   en draft hasta resolver los gates de P03; no activarlo solo por compilar.
5. Backup y restore aislado del estado persistente antes del rollout autorizado.
   Las pruebas desechables de migración no son el respaldo del DEV real.
6. Terminar sesiones de Keycloak al sancionar, con un mecanismo realmente acotado
   y pruebas de privilegios negativos; sigue pendiente. No otorgar administración
   general a los lectores de standing o al provisionador de `compa` para resolverlo.

La revisión del código oficial de [Keycloak 26.8.1, UserResource](https://github.com/keycloak/keycloak/blob/26.8.1/services/src/main/java/org/keycloak/services/resources/admin/UserResource.java)
confirma que `logout()`, modificar y borrar usuarios exigen el mismo control
`requireManage(user)`. Por eso un grant de gestión no equivale a una identidad
limitada a cerrar sesiones. Ese efecto debe diseñarse y probarse con un límite
real de privilegios; no se declara resuelto por los tokens cortos ni por standing.
La recuperación de un evento antiguo tampoco debe cerrar sesiones nuevas después
de una reversión. El principal técnico actual conserva su alcance previo.

Los avisos jurídicos completos, casos, apelaciones y atribución de decisiones
humanas pertenecen a P11; documentos a P04, identidad baneada a P05 y privacidad
completa a P12. No se presentan como funciones existentes. La cuenta técnica
actual que asigna `compa` no recibe administración general para cerrar sesiones:
ese efecto requiere un mecanismo acotado y pruebas antes de activarse. El control
de standing no depende de que Keycloak cierre una sesión.
