# P03 — Avisos de estado de cuenta

Implementación de V026, incorporada inicialmente con rac-platform v0.7.0 y
actualizada a v0.8.0 para la evaluación temporal. Complementa la recuperación de
reservas de [P03-recovery](P03-recovery.md). El preview sigue desactivado en el
DEV persistente; esta entrega no cierra todos los criterios de P03.

## Entrega y privacidad

`standing-alert-consumer` usa una identidad AMQP y el rol PostgreSQL
`rac_standing_alert` propios. Consume `rac.alert.standing`, una cola quorum con
reintentos y cola fallida separados de match. El evento original, su versión y
un hash canónico de todos sus metadatos se registran en el inbox, junto con el
aviso, en una transacción. Solo después se confirma el mensaje al broker.
Una entrega repetida no crea otro aviso ni cambia su fecha de lectura. Una
identidad/versión reutilizada con contenido distinto se envía a cuarentena;
allí se conserva únicamente hash, motivo técnico y fecha, nunca el payload.

El aviso dice «Actualización de tu cuenta». Es deliberadamente neutral: un
evento histórico recuperado no afirma que la cuenta siga suspendida. No lleva
motivos privados, detalles de casos ni una reserva ficticia. `sesion_id` es
`null` para `estado_cuenta`; el CHECK de la BD exige referencia de reserva para
los otros tipos. Flutter conduce estos avisos al perfil, donde el estado actual
se consulta a la autoridad. La bandeja y marcar como leído conservan el control
de propietario existente. No se han activado correo, push ni proveedores externos.

## Recuperación independiente

El cliente técnico `rac-alert-standing` puede consultar historial y descubrimiento,
pero no los snapshots usados para autorizar acciones comerciales. Chat solo
puede consultar snapshots; match puede consultar snapshots e historial. User
valida la identidad de cada cliente y el propósito de la ruta en su listener
interno, sin publicarlo en nginx ni en un puerto del host.

La autoridad descubre cuentas modificadas mediante páginas ordenadas de hasta
100 IDs. Esto incluye cuentas sin reservas. Un barrido siguiente encuentra
cambios que hayan quedado detrás del cursor anterior. Por cuenta se solicitan
páginas contiguas de hasta 50 eventos originales; nunca se fabrica una identidad
para reconstruir un aviso. La inserción concurrente vía broker y la recuperación
usan el mismo inbox y deduplicación.

Los claims duran cinco segundos y tienen token de fencing. No se mantiene un
lock SQL durante HTTP. Un proceso reemplazado no puede adelantar el cursor del
nuevo dueño; ante fallo se vuelve a intentar y los efectos ya confirmados se
deduplican. El worker limita cada ciclo a 20 cuentas y cinco segundos. Readiness
exige broker, BD y un barrido completo reciente, sin historial pendiente ni
cuentas sin contrastar durante 15 segundos. El lag es `+Inf` si aún no existe
un contraste completo o queda historial pendiente.

Prometheus observa conexión, recuperación, cola fallida y presencia durable de
cuarentena. No hay labels con IDs de usuarios. Un reinicio no borra la alerta de
cuarentena. No borrar inbox, cursores ni credenciales para resolver una alerta.

## Credenciales y despliegue

Los secretos se escriben antes de modificar el broker y solo se montan en su
consumidor, como lectura. Si falta un archivo pero la identidad ya existe, el
bootstrap falla con una instrucción de recuperación; no rota una contraseña
silenciosamente y deja consumidores existentes sin acceso. Recuperar el volumen
o realizar una rotación explícita y coordinada.

Antes de activar: detener workers antiguos, respaldar, comprobar restore aislado,
aplicar V026 y desplegar las revisiones coordinadas del manifiesto. Provisionar
el tercer lector de identidad y las colas/credenciales. Habilitar el overlay solo
en DEV y comprobar permisos negativos, readiness, replay y métricas antes de
abrir escrituras. En QA/PRD no se permite HTTP interno por la excepción DEV.

## Evidencia y límites

`test_messaging.py` exige que se ejecuten, sin skip, las suites PostgreSQL y
RabbitMQ de avisos: duplicados concurrentes, ACK perdido y redelivery con lector
restringido, rollback/reintento, lectura propia, preservación de leído, conflictos
de todos los metadatos y cuarentena sin contenido. La recuperación HTTP prueba
suspensión perdida seguida de reversión, cuenta sin reservas, caída de autoridad,
claims vencidos, fencing y páginas múltiples. El descubrimiento usa 102 cuentas
y comprueba cambios detrás del cursor. `test_identity_permissions.py` comprueba
los tres clientes con Keycloak real y ausencia de privilegios administrativos.

Estas pruebas no acreditan todavía el p99 de revocación/latencia ni completan
casos y apelaciones de P11. La notificación neutral no reemplaza los avisos
jurídicos versionados de esa entrega.
