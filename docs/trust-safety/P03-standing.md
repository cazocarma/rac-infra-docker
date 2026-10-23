# P03 — Estado de cuenta (en desarrollo)

D02 y D03 fueron confirmadas por el usuario el 22 de octubre de 2026.
La matriz y el alcance del cupo están en [ADR-001](ADR-001-standing.md).

## Autoridad interna y reservas (implementadas, preview desactivado)

User consume `rac-platform v0.4.0` y ofrece el handler compartido con fuente
PostgreSQL bajo su propio rol. Escucha en un servidor separado en el puerto 8082,
sin publicación de puerto al host ni ruta en el router público o nginx.
`/internal/standing` exige identidad de servicio; no acepta JWT del frontend.
La configuración inválida impide iniciar el listener cuando se habilita el flag.

`identity_standing.py` provisiona `rac-standing` como recurso bearer-only y
`rac-match-standing` como cliente confidencial sin flujos de usuario, sin
full scope, con cuenta de servicio, audience y rol de cliente `standing.read`.
Retira asignaciones directas previas de roles/scopes y no concede privilegios de
administración. Guarda primero el secreto para poder reintentar un bootstrap
interrumpido; las ejecuciones siguientes lo conservan. Si existe el cliente pero
se perdió su volumen, exige restauración o rotación explícita. Solo match monta
ese secreto; user recibe únicamente el mapa client ID -> subject técnico.

Match protege creación, aceptación y extensión de reservas en el repositorio,
no solo en middleware. Resuelve los subjects desde identidades persistidas;
requiere `request_booking` del cliente y `accept_booking` del compa. No permite
que un rol admin omita esos requisitos sobre los participantes. Las operaciones de
aceptación y extensión exigen además que actúe el compa o cliente titular,
respectivamente: un admin comercial no representa consentimiento de terceros.
Las consultas de
ambos participantes se ejecutan en paralelo y generan leases con un plazo común
de dos segundos desde antes de consultar. La transacción SQL usa ese contexto:
consultas, esperas por locks y escritura consumen el mismo presupuesto.

Inmediatamente antes del commit consulta otra vez las versiones de ambos y
reevalúa las restricciones temporales sin renovar el lease. Una versión nueva,
autoridad indisponible o permiso vencido revierte escritura, cupo y eventos de
esa transacción. La denegación devuelve 403 con código público estable; una
autoridad indisponible devuelve 503. Cancelación propia conserva autenticación,
propiedad y reglas de negocio, sin depender de disponibilidad de la autoridad.
La extensión solo actualiza una reserva que siga activa al escribir.

**Límite de concurrencia:** esto no es un bloqueo distribuido ni garantiza que
una sanción confirmada justo después de la última lectura preceda al commit en
otra BD. Conserva la ventana acotada del lease; la reconciliación V024 descrita
abajo recupera reservas que confirman después del primer pase del evento.
No se declara aún el objetivo
p99 de revocación ni el objetivo de latencia del hot path.

## Envío de chat en preview

Chat consume platform v0.4.0 con vendor generado y un cliente técnico propio
`rac-chat-standing`, separado del secreto de match. El bootstrap conserva ambos
secretos en volúmenes independientes; user solo recibe sus subjects públicos.
La configuración habilitada falla al arrancar si faltan credenciales o transporte
válido. El preview DEV monta únicamente el secreto de chat en ese servicio.

Antes de iniciar la transacción de envío se verifica pertenencia a la reserva y
se consultan ambos participantes para `send_message`. El contexto de la
transacción conserva el plazo del permiso, incluidos los locks de reserva y de
idempotencia. Justo antes del commit se verifican otra vez las versiones;
denegación revierte mensaje y outbox juntos. Admin no reemplaza pertenencia.
Una repetición ya persistida conserva la idempotencia, pero también exige pasar
la autorización inicial cuando este preview está habilitado.

Historial, seguridad, bloqueo y reportes mantienen sus verificaciones de
autenticación/propiedad independientes de standing. No se desconectan esos
canales por una caída de la autoridad. Falta reflejar la restricción en
`can_send`/Flutter: el servidor ya rechaza envíos, aunque la UI pueda ofrecerlos.
Las pruebas de chat cubren ambas partes sancionadas, autoridad caída, lectura y
bloqueo disponibles, cambio de versión al commit, rollback y reintentos. El
escenario de negocio usa una fuente de prueba; JWT/firma y el bootstrap real
de Keycloak se validan por las suites separadas, sin afirmar un E2E completo.

## Detalle de reconciliación V024

`match_booking_standing` guarda las versiones de cliente y compa usadas para
crear, aceptar o extender una reserva. Se escribe en la misma transacción de
negocio, se revierte si falla la autorización final y no permite degradar una
versión ya guardada. `Permit.Version` expone esa procedencia; leerla no autoriza
nada ni renueva el permiso. Solo rac_match escribe esos registros; el worker y
el respaldo leen. Sin enforcement habilitado no se inventa una prueba de
autorización para datos antiguos.

El consumidor conserva en su proyección el evento auténtico de inbox que
estableció la versión. La migración enlaza proyecciones V023 existentes a su
evento y aplica una FK compuesta de evento/subject/versión; un historial
inconsistente impide migrar en vez de generar un evento ficticio.

La activación debe coordinar V024 con la nueva imagen del consumidor: detener
el consumidor anterior antes de migrar y luego arrancar el nuevo. El código
anterior no escribe source_event_id y sus actualizaciones fallarían las nuevas
constraints; la entrega queda sin ACK para reintento, pero no es un despliegue
rolling compatible. No retroceder el esquema ni borrar inbox para resolverlo.
Este paso se añade al ensayo de actualización/restauración antes del rollout.

El primer pase y el reconciliador comparten la implementación de efectos.
Procesan hasta 100 reservas por subject y transacción, tomando locks de compa
ordenados antes de los locks de reservas. La reconciliación procesa hasta 20
subjects por ciclo, con timeout de cinco segundos y cadencia de un segundo.
Los subjects se ordenan por el último pase para repartir el trabajo; varios
workers usan `FOR UPDATE SKIP LOCKED` y comparten la misma idempotencia.

Un evento v2 no afecta una reserva cuya autorización para ese participante ya
es v3, aunque la reversión v3 aún no haya llegado al broker. La procedencia se
vuelve a consultar en una sentencia posterior al lock de reserva: una lectura
hecha antes de esperar el lock podría haber quedado obsoleta. Los registros
legados sin procedencia se tratan conservadoramente como anteriores al evento;
por eso este preview no habilita sanciones operativas con escritores sin cubrir.

Una reserva confirmada tarde con autorización v1, después de procesar una sanción
v2, se recoge en el siguiente pase. Se conserva el event ID original; cancelación,
devolución a contraparte y registro del efecto confirman juntos. Los efectos de
revisión de actividades iniciadas no se duplican y una reversión no reabre nada.
Una falla SQL revierte todo ese pase y permite reintentarlo.

El loop corre en standing-match-consumer incluso si se pierde la conexión al
broker, usando exclusivamente eventos ya recibidos. Readiness exige un ciclo
exitoso en los últimos 15 s; hay contadores de subjects/fallas, timestamp del
último éxito y una alerta por más de 30 s sin éxito sostenido durante un minuto.
Esto no es una resincronización desde la autoridad: pérdida de historial del
broker/inbox, reconstrucción de proyecciones y otros dueños siguen pendientes.

Pruebas desechables con roles reales: commit posterior al primer efecto,
autorización nueva ante sanción atrasada, cambio de procedencia mientras el
worker espera un lock, consumidores concurrentes, devolución única, fallo de
inserción con rollback/reintento, reversión y más de dos páginas de reservas.
La actualización desde V023 preserva event ID y estado. No se aplica esta
migración a la base DEV existente durante el desarrollo.

## Autenticación de lectores internos

User incorpora `platform.NewStandingReader`, un autenticador separado de la
herencia de roles de la API pública. Verifica firma RS256 con JWKS, issuer,
audience dedicada, expiración, issued-at, not-before y vida máxima de 300 s.
Exige además `azp` permitido, el subject exacto de su cuenta de servicio
provisionada y el rol de cliente `standing.read` en esa misma audience.
Un usuario admin, un rol de realm o un permiso en otra audience no bastan.
La configuración inválida falla al construir; HTTPS es obligatorio salvo la
opción explícita de desarrollo. La consulta JWKS tiene timeout y no sigue
redirecciones. Los errores de autenticación no incluyen el token.

Las pruebas usan JWT RS256 realmente firmados y un servidor JWKS desechable;
cubren firma incorrecta, issuer/audience, usuarios humanos, vinculación
cliente/subject, permisos, caducidad, fechas futuras, duración excesiva y
cabeceras duplicadas. Pasan `go vet ./...` y `go test -race ./...` de user.
La suite desechable de Keycloak comprueba el cliente provisionado, estabilidad
de secreto, ausencia de refresh token y rechazo de password grant/admin APIs.
Go verifica el JWT real contra JWKS real. La suite de PostgreSQL/HTTP comprueba
el mismo JWT de usuario anterior a una sanción contra dos instancias de match,
denegación por cualquiera de las partes y conservación de cancelación propia
durante caída de autoridad. Las carreras antes del commit comprueban rollback
de creación, aceptación, extensión y cupo; una espera por lock vence el lease.
Las pruebas de permisos de máquina y negocio son escenarios separados, no una
medición de carga del stack completo.

## Build y ensayo explícito

User, match y chat usan vendoring generado según [ADR-008](ADR-008-private-go-dependencies.md).
Los builds Docker y pruebas independientes no reciben credenciales de platform.
El CI integrado compara las reglas generadas con el checkout fijado de platform.

`STANDING_PREVIEW=1` añade `compose.standing.yaml` únicamente para DEV. Make
provisiona identidad antes de iniciar APIs; los volúmenes de lectura y secreto
están separados y montados read-only. QA/PRD rechazan este preview: requieren
transporte TLS verificado y rollout completo. El flag no está habilitado en el
stack existente y no se aplicaron migraciones a los datos del usuario.

Antes de ensayar sobre ese DEV hay que cumplir el respaldo consistente y la
restauración aislada de P02. En un entorno desechable preparado, desde infra:

```sh
make ENV=dev STANDING_PREVIEW=1 config
make ENV=dev STANDING_PREVIEW=1 up
```

Es un preview de **reservas y envío de chat**, no un control completo de la plataforma. Publicar
perfil, disponibilidad, reseñas, catálogo/medios y otras superficies
siguen pendientes. No habilitar sanciones operativas como si todo P03 estuviera
completo. Deshabilitar el flag retira este enforcement y requiere un rollback
operativo deliberado, no un fallback automático por fallas de autoridad.

## Entrega local: motor compartido

`rac-platform/standing` implementa evaluación de capacidades y restricciones
temporales. Mantiene canales de protección aun con cuenta suspendida/baneada o
autoridad indisponible. La excepción requiere autenticación y propiedad en cada
adaptador; no concede acceso a recursos ajenos.

Los leases duran como máximo dos segundos desde el inicio de la petición a la
autoridad, consumiendo la latencia de red. Una versión posterior invalida el
lease; eventos antiguos no lo prolongan. Se copian las restricciones para que
el llamador no pueda mutar una autorización emitida. El adaptador deberá usar
reloj monotónico local y no reconstruir leases desde timestamps del broker.

`AuthorityAuthorizer` ofrece el camino síncrono sin caché: consulta una fuente
autenticada y su versión más reciente. Niega operaciones comerciales ante error,
versión ausente o respuesta tardía, sin filtrar diagnósticos privados. La fuente
concreta está conectada al preview descrito arriba. El resultado no sustituye el control de
versión y autorización al commit de la operación de negocio.

El contrato todavía no publicado de `user.standing.changed.v1` incluye las cinco
capacidades nuevas y exige los siete canales de protección en todos los estados.
Suspensión/ban no pueden anunciar permisos comerciales.

## Entrega local: persistencia de autoridad V020

`standing.account` referencia al usuario real y conserva versión monotónica.
V020 inicializa usuarios existentes como active/version 1 y un trigger crea el
estado de nuevos usuarios dentro de su transacción. No modifica roles Keycloak.
Las restricciones solo pueden afectar las cinco capacidades comerciales; los
canales de protección no se pueden restringir por esta vía.
El estado inicial sigue el ciclo de vida de usuario mediante FK en cascada. Un
usuario con eventos de enforcement no puede borrarse físicamente por esa vía:
la referencia restrictiva del outbox impide eliminar su historial. Esto no define
plazos legales de retención ni sustituye el futuro flujo de privacidad.

`standing.change_account` bloquea la fila, exige versión esperada y guarda estado,
restricciones, auditoría y outbox en la misma transacción. Event ID repetido con
el mismo comando devuelve el evento original; contenido diferente o versión
obsoleta falla. Los registros de comando contienen solo referencias, estados,
capacidades y fechas; no aceptan una justificación privada libre.

La función no se concede a roles de aplicación. Un principal de auditoría debe
estar provisionado para el login autenticado o toda la transacción falla. No se
activa una API de sanciones antes de conectar autorización staff, revisión de
casos y política aprobada. El actor auditado sigue siendo el servicio, no una
persona staff verificada.

Solo rac_user lee la autoridad; otros servicios no reciben acceso a esas tablas.
`rac-platform/standing/postgres` proporciona el adaptador de lectura del dueño:
liga el subject OIDC a usuario, obtiene estado/restricciones en un snapshot SQL y
devuelve errores opacos. El publicador y el consumidor de match se describen abajo.
El respaldo tiene lectura y el bootstrap incluye el nuevo esquema al reconciliar
propiedad, sin ampliar permisos de otros servicios.

## Entrega local: efectos de reservas V021

Match mantiene inbox, proyección monotónica y efectos en tablas propias.
`Repositorio.ApplyStanding` recibe una entrada interna validada por el futuro
consumidor autenticado, no una petición HTTP. La huella del inbox cubre la entrada
semántica de match (evento, usuario, versión y estado); el transporte deberá
validar el contrato completo. Las entregas duplicadas se confirman sin repetir
efectos; un mismo evento con contenido distinto o misma versión con estado
contradictorio falla. Versiones anteriores no revierten la proyección.

Suspensión/ban cancela pendientes y activas cuyo inicio aún es futuro al procesar
el evento. La comparación usa el reloj de PostgreSQL después de bloquear las
reservas, no la fecha de emisión ni el reloj del consumidor. Si el sancionado es
cliente, restituye el registro de cupo de su compa contraparte sin cambiar la
semana original. Si es compa, no devuelve su propio cupo. Una activa ya iniciada
conserva estado y genera un efecto durable `safety_review`, todavía pendiente de
ingreso al módulo de casos. Las finalizadas y canceladas permanecen intactas.

Los efectos, cambios de estado, devolución, inbox y proyección confirman juntos;
la cancelación genera el evento de reservas mediante el trigger existente.
Se toma el mismo lock de proveedor que usa la aceptación de cupos. Una reversión
solo actualiza la proyección; no reactiva ninguna reserva.

Los efectos de V021 se conectan ahora a los workers descritos abajo. Falta el
control autoritativo en nuevas escrituras, su comprobación al commit y
reconciliación. La proyección no es un lease fresco y no debe usarse para
autorizar operaciones por sí sola.

## Entrega local: RabbitMQ y workers V023

`standing-events-relay` publica únicamente filas confirmadas de standing.outbox.
Reutiliza el relay de transporte de la imagen match, seleccionando un stream
cerrado (booking o standing), sin aceptar identificadores SQL arbitrarios. La
autoridad sigue siendo user: compartir el binario no concede a rac_match acceso
a sus tablas. El worker tiene login `rac_standing_relay`, lectura del outbox y
UPDATE únicamente de confirmación/reintentos; no puede cambiar sanciones.

`standing-match-consumer` tiene identidad propia `rac_standing_match`: columnas
mínimas de reservas/cupos, inbox/proyección/efectos y cuarentena. No puede leer
correo ni modificar la autoridad. Los volúmenes de credenciales AMQP son separados
y de solo lectura para cada worker. Solo el bootstrap recibe el administrador.

El exchange durable rac.standing dirige user.standing.changed.v1 a una cola quorum
propia de match. El publicador usa mandatory y publisher confirms; ante fallo
conserva el evento y programa reintento sin límite de intentos. El consumidor usa
prefetch 1, ACK manual después del commit y reconexión con pausa. Un mensaje
inválido/conflictivo se confirma solo tras guardar su SHA-256 y motivo técnico;
no se guarda el cuerpo privado en SQL ni en logs. Reintentos de infraestructura
agotados quedan en cola quorum de fallidos mediante dead lettering at-least-once.

El bootstrap se verifica dos veces contra el broker real: conserva credenciales,
topología y ACL. La salud del broker comprueba listeners AMQP y management antes
de configurar; un simple ping no acredita que la API de administración esté lista.
Hay readiness, métricas sin etiquetas de usuario y alertas de atraso, desconexión
y cola de fallidos. La cuarentena mínima todavía requiere el futuro flujo de
revisión/retención; no se borra automáticamente ni se reenvía sin inspección.

En laboratorio desechable se probó autoridad -> outbox -> broker -> consumidor
con credenciales restringidas: cancelación y devolución única, entrega duplicada,
caída de publicación, pérdida de ACK tras commit y reversión sin reapertura.
No se han activado estos workers ni V023 en la base DEV del usuario.

## Evidencia local

- Go 1.27.2 en contenedor: `gofmt`, `go vet ./...`, `go test -race ./...`.
- Pruebas de estados desconocidos, restricciones malformadas, límites temporales,
  modificación de snapshots, autoridad caída/lenta, versión obsoleta y protección.
- Contratos: suite Python con `jsonschema[format]==4.25.1`, contenedor desechable.
- Desde RAC: `make -C rac-infra-docker test-standing-authority`: PostgreSQL desechable, rollback por auditoría
  ausente, replay, conflictos, restricciones inválidas, concurrencia y grants.
  La prueba también está incorporada al workflow de CI; no implica ejecución
  remota ni activación en DEV.
- Suite de migraciones: instalación fresca, adopción de usuarios existentes,
  checksum y regresiones de cupos, chat y alta de compa.
- Suite de permisos: migrador sin superusuario, reconciliación del esquema
  standing, lecturas limitadas al dueño y respaldo/restauración con ACL.
- Match Go: `go vet ./...`, `go test -race ./...`; en PostgreSQL desechable,
  sanción de cliente versus compa, futuras versus iniciadas/finalizadas,
  devolución a contraparte, fallo a mitad de transacción, entrega duplicada en
  paralelo, ID/versión contradictorios y reversión seguida de evento antiguo.
- `test_messaging.py`: broker y PostgreSQL reales desechables, bootstrap repetido
  con ACL y políticas quorum, publicación/consumo con logins restringidos,
  duplicados, cuarentena y redelivery tras commit sin ACK. Sin secretos de DEV.
- Configuración dev/qa/prd, Prometheus/promtool y once reglas de alertas válidas.

La revisión anterior `72b489e` terminó con cuatro checks remotos correctos,
verificados en el [PR #8](https://github.com/cazocarma/rac-infra-docker/pull/8).
Eso confirma el preview anterior de autoridad/reservas; V024 y la reconciliación
de esta entrega cuentan con las pruebas locales descritas y requieren el nuevo
CI de sus SHAs fijados.

La ejecución remota [39956656284](https://github.com/cazocarma/rac-infra-docker/actions/runs/39956656284)
pasó los cuatro jobs (incluida integración) con el commit anterior eceed7a. Esa
evidencia confirma la corrección V022 y la base previa, no los workers V023
añadidos después; estos tienen las pruebas locales anteriores y un nuevo CI al
publicar esta revisión.

## Pendiente para completar P03

1. Verificar Actions con estas revisiones y completar el rollout del enforcement,
   que sigue desactivado en el DEV existente.
2. Conectar la autoridad al ingreso autenticado de staff y a políticas aprobadas;
   consumidores de otros dueños y resincronización desde la autoridad.
3. Integración de todos los escritores y contrapartes, catálogo y medios,
   invalidación, reconciliación de otras superficies, controles al commit restantes y aviso en Flutter.
4. Conectar los efectos pendientes de revisión al módulo de casos y probar
   integración de los workers con los controles autoritativos concurrentes.
5. Completar E2E de todos los escritores, particiones broker/autoridad y carrera
   posterior al último check; medir latencia bajo carga definida. Los escenarios
   locales de reservas con JWT anterior, dos instancias y pre-commit ya pasaron.

No hay enforcement nuevo activado ni migraciones P03 aplicadas al DEV existente.
Las pruebas unitarias no prueban el objetivo de revocación p99 de cinco segundos.

## Transporte de autoridad preparado (v0.2.0)

El módulo privado `cazocarma/rac-platform` está publicado con tags inmutables
v0.1.0 y v0.2.0. La versión 0.2.0 añade el transporte HTTP de standing y proveedor
OAuth2 client credentials. HTTPS verificado es obligatorio fuera del permiso
explícito de HTTP para DEV; las redirecciones se rechazan tanto para consulta
como para emisión de tokens. Se acotan tiempos, tamaño y subject de respuestas.

El secreto se lee desde archivo montado; no se guarda en URL, logs ni imágenes.
Tokens con duración superior a 300 s o tipo incorrecto se rechazan. Renovaciones
simultáneas se serializan y el token se retira de caché antes de su vencimiento.
No hay refresh tokens ni un autenticador permisivo por defecto en el handler.

Pruebas locales Go con `-race`: autoridad suspendida/no disponible, autenticador
ausente, redirecciones sin transmisión a destino, respuestas de otro subject,
cuerpos inválidos/excesivos, fallos de credenciales y renovación concurrente.
Estas pruebas iniciales de transporte usan identidad técnica de fixture.
Las pruebas posteriores de JWT real, cliente provisionado y reservas se
describen al inicio de este documento; no equivalen a completar todo P03.

El usuario autorizó añadir únicamente rac-platform a la App RAC CI Read con
Contents de lectura. La instalación se guardó y verificó con ocho repositorios seleccionados,
conservando los siete existentes y acceso de lectura a código/metadatos. El CI
integrado remoto 39956656284 pasó con el nuevo acceso.


## Escritores user y coherencia del chat (avance 2026-10-23)

El preview de standing ahora comprueba publicaci�n/edici�n de compa, alta de
skills y rese�as verificadas. Las rutas antiguas de publicaci�n usan la misma
autoridad. La autorizaci�n tiene un plazo acotado y vuelve a comprobar versiones
antes del commit; una sanci�n durante el provisionamiento revierte las escrituras
locales. La asignaci�n remota del rol gratuito es idempotente y no concede una
excepci�n a standing, aunque puede haber ocurrido antes del rollback local.

Las rese�as requieren standing tanto del autor como de la contraparte. Seguridad,
lecturas propias e historial autenticado conservan sus comprobaciones de acceso
sin el bloqueo comercial. GET /api/user/me/standing devuelve estado, versi�n y
capacidades �nicamente del sujeto autenticado; no expone caso ni detalles de
restricciones. Con el preview desactivado informa enforcement_enabled=false,
sin fingir una decisi�n autoritativa.

El cat�logo aplica el filtro de standing en SQL antes de LIMIT/OFFSET, con orden
estable para empates; detalle, rese�as p�blicas y foto usan la misma condici�n
de visibilidad. Restricciones de publicaci�n vencidas dejan de ocultar el perfil
sin requerir un evento nuevo. Las lecturas propias siguen disponibles.

Historial, eventos y seguridad del chat consultan standing para can_send. Una
sanci�n o fallo de autoridad devuelve can_send=false sin impedir la lectura; el
env�o posterior siempre adquiere su propia autorizaci�n y no conf�a en ese hint.

Verificaci�n: go vet y go test -race en user/chat; PostgreSQL desechable con
roles rac_user/rac_chat para bloqueo de participantes, rollback concurrente,
aliases antiguos y lecturas protegidas. La suite completa de migraciones pas�
antes del �ltimo filtro de cat�logo; su actualizaci�n pas� adem�s con
`python scripts/test_migrations.py --services user`. La opci�n limita las suites
Go seleccionadas, pero conserva instalaci�n fresca, adopci�n y validaciones de
integridad/checksum de todas las migraciones. No activa el preview en DEV.

Pendientes: integrar el aviso en Flutter, escritores de disponibilidad/medios,
resincronizaci�n desde autoridad y mediciones de revocaci�n/latencia. Este avance
no completa P03 ni acredita cumplimiento jur�dico o del objetivo p99.


## Agenda y reemplazo de fotos (avance 2026-10-23)

Match aplica publish_listing a la disponibilidad semanal y al alta/borrado de
bloqueos de agenda. Comprueba tanto al due�o como al actor que la modifica, sin
excepci�n por rol admin. El repositorio de time-off recibe la misma fuente que
el servidor; ya no crea una ruta sin autoridad. Las transacciones vuelven a
comprobar el permiso antes del commit, incluso al reintentar un bloqueo existente.
Las lecturas propias de agenda permanecen disponibles durante un fallo de autoridad.

User comprueba publish_listing para reemplazar la foto despu�s de normalizarla
y antes de abrir la transacci�n. Al finalizar la escritura del objeto vuelve a
comprobar la versi�n; si hay una sanci�n concurrente, conserva la referencia
anterior y elimina el objeto nuevo. Consultar y borrar la foto propia no requiere
permiso comercial. Los errores de commit con resultado incierto siguen conservando
el objeto para no romper una referencia que pudiera haberse confirmado.

Evidencia local: go vet y go test -race en ambos servicios. PostgreSQL migrado
desechable con roles rac_match/rac_user: due�o o actor suspendido, autoridad ca�da,
lectura protegida y rollback de borrado de time-off revocado durante el commit;
foto suspendida, sanci�n durante Put, referencia preservada y ausencia de objeto
local sobrante. La ruta local del almacenamiento fue ejercitada; el subtest S3
requiere su fixture y no se presenta como ejecutado en esta ronda.
`test_migrations.py --services match` pas�, incluyendo adopci�n, integridad y
checksums. El runner incorpora cach� de compilaci�n de match y exige evidencia
del subtest schedule-writers para evitar que una omisi�n silenciosa se anuncie
como cobertura. Contin�an pendientes Flutter, otros escritores de perfil,
resincronizaci�n, pruebas amplias de fallo y mediciones de latencia.
