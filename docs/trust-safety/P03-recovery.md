# P03: recuperación autoritativa de sanciones

Estado: implementada y probada localmente en infraestructura desechable. No se
ha activado en el DEV persistente. P03 sigue abierto por el resto de sus gates.

## Por qué no basta consultar el estado actual

Una suspensión v2 puede perderse en el broker y una reversión v3 llegar antes.
La proyección v3 no prueba que se procesaron los efectos de v2. Leer solo el
último estado omitiría cancelaciones que la reversión no debe deshacer (D03).

El cursor de recuperación es independiente de la versión de la proyección.
Recorre todos los eventos originales desde v2: v1 es la cuenta inicial activa,
creada por el trigger, y no es un evento de cambio. El contrato rechaza cambios
con standing_version menor que 2. No se fabrican IDs ni eventos sintéticos.

## Autoridad y transporte

rac-platform v0.6.0 incorpora ReplayHead y ReplayPage. El primero permite
contrastar la versión actual y su evento original; el segundo recupera hasta
50 cambios consecutivos de una cuenta. Consulta cuenta y outbox en un solo
snapshot SQL, usando el índice único (subject_id, standing_version).

El protocolo rechaza regresiones, huecos, otra cuenta, otra posición inicial,
versiones no contiguas y páginas incompletas respecto de su head. El consumidor
valida además cada evento con el mismo decoder estricto del broker, incluidos
campos exactos, duplicados, capacidades y referencias. Estas lecturas no son
leases y no autorizan escrituras comerciales.

Las rutas son POST /internal/standing/replay y
POST /internal/standing/replay/events, en el listener separado de user. Exigen
el cliente rac-match-standing ligado a su subject técnico, con JWT RS256 de
issuer/audience/rol/lifetime válidos. Un JWT válido de rac-chat-standing puede
consultar standing de participantes, pero no acceder a recuperación histórica.
No existen estas rutas en el router público ni una excepción para admin humano.

Las llamadas usan client credentials, secreto en volumen de solo lectura,
timeout de 1,5 s, límites de cuerpos y rechazo de redirects. HTTPS se exige
fuera del permiso DEV explícito. El overlay sigue restringido a DEV hasta que
la infraestructura de TLS y el rollout correspondiente estén completos.

## Estado durable y concurrencia

V025 añade match_standing_sync con cursor, último contraste y claim UUID de
cinco segundos. Un trigger del dueño de la BD registra ambos participantes de
cada reserva; la migración incorpora participantes ya existentes. Solo el
consumidor puede modificar estos cursores. Se conserva también el último head
observado: completar una página de 50 eventos no equivale a terminar el historial.

El worker toma un claim atómico con FOR UPDATE SKIP LOCKED y libera la conexión
antes de consultar HTTP. Otro proceso recupera un claim vencido. La actualización
final exige el token original: un worker atrasado no puede sobrescribir el cursor
de quien tomó el relevo. Si falla una página, no avanza el cursor. Los eventos
ya confirmados se reproducen con sus IDs originales y sus efectos idempotentes.

match_standing_sanction conserva cada suspensión/ban como trabajo independiente
del estado actual. Una reversión no elimina lotes pendientes. Se puede recuperar
una sanción antigua sin bajar la versión de la proyección: su efecto solo alcanza
reservas cuya prueba de autorización no sea posterior. Una reserva con permiso
v3 sobrevive al replay de v2. Las reservas legacy sin prueba se tratan de forma
conservadora. Una actividad ya iniciada genera revisión de seguridad; no se
reabre una reserva cancelada ni se devuelve dos veces su cupo.

La identidad de cada versión es única también en inbox. Dos IDs distintos para
la misma cuenta/versión se rechazan como conflicto, aunque tengan el mismo estado.
El ledger referencia la identidad durable del inbox, sin permitir que la API
fabrique procedencia de eventos.

## Permisos y observabilidad

rac_user puede leer únicamente event_id, subject_id, standing_version y payload
del outbox para servir la recuperación. No puede leer command ni escribir ese
outbox. rac_standing_match no accede directamente a la autoridad de user; usa el
transporte autenticado. rac_match pierde DML sobre proyecciones/inbox/efectos.
El nuevo ledger y los cursores se escriben solo con rac_standing_match; backup
conserva SELECT. No se otorgaron permisos de mutación de sanciones a aplicaciones.

El worker procesa hasta 20 cuentas por ciclo, con presupuesto de cinco segundos,
además de la reconciliación de efectos. Su readiness exige contraste reciente
de las cuentas y ciclos correctos; una cuenta atascada no se oculta porque otras
sigan procesándose. Expone últimos éxitos, fallos, cuentas y lag máximo, sin
labels de usuario. El lag es +Inf mientras no haya un contraste completo o
queden páginas pendientes; no se inventa una duración para ese estado desconocido.
RACStandingRecoveryDelayed alerta ante lag mayor que 30 s
durante un minuto. Esto observa recuperación; no acredita el SLO de revocación.

## Evidencia local

- go vet y go test -race en platform, user, match y chat.
- TestStandingRecoveryPostgresHTTP usa autoridad PostgreSQL con rac_user,
  transporte HTTP autenticado y rac_standing_match. Recupera suspensión perdida
  seguida de reversión, preserva autorización nueva, devuelve cupo a contraparte,
  no avanza durante caída, prueba claims concurrentes/vencidos y fencing, detecta
  huecos y conserva el ID original. No usa RabbitMQ para conseguir los eventos.
- TestStandingReconciliationPostgres mantiene trabajo histórico tras reversión,
  repara más de un lote y conserva rollback/reintentos y pruebas de autorización.
- TestStandingReaderSignedTokens rechaza el JWT válido de chat en ambas rutas
  de replay, sin confundir una restricción por propósito con una firma inválida.
- test_migrations.py pasó con todas las suites y se repitió para match tras el
  ajuste final de ACL. La recuperación usa una BD desechable separada para no
  compartir candidatos con tests que corren en paralelo.
- test_database_permissions.py pasó para instalación fresca y adopción desde
  V018, migrador sin superusuario, columnas permitidas/prohibidas y backup/restore.
- check_go_vendor.py confirma que los tres consumidores corresponden a la misma
  versión inmutable del módulo compartido. Build Docker de match correcto.
- Contratos JSON y las doce reglas Prometheus correctos. test_messaging.py pasó
  con RabbitMQ real: roles/topología, confirmaciones, rollback, replay, ACK perdido
  y cuarentena. El CI remoto de estos SHAs debe confirmarse antes de liberar.

## Rollout y pendientes

No aplicar V025 con workers antiguos en ejecución. Detener los consumidores,
respaldar y probar restore aislado, migrar, desplegar las revisiones fijadas y
habilitar el preview con identidad configurada. Validar readiness, cursor/lag,
permisos negativos y replay antes de abrir escrituras. No borrar cursores ni
inbox como forma de resolver un incidente; investigar integridad/procedencia.

La recuperación de match no sustituye las notificaciones de standing de alert,
los módulos de casos/ingreso staff, ni las pruebas de partición y mediciones
pendientes del plan completo. No hay conformidad jurídica acreditada por esta
implementación, ni servicios externos o cobros activados.
