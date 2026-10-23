# P03 — Estado de cuenta (en desarrollo)

D02 y D03 fueron confirmadas por el usuario el 22 de octubre de 2026.
La matriz y el alcance del cupo están en [ADR-001](ADR-001-standing.md).

## Autoridad interna y reservas (implementadas, preview desactivado)

User consume `rac-platform v0.3.0` y ofrece el handler compartido con fuente
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
otra BD. Conserva la ventana acotada del lease; los efectos por eventos y la
reconciliación pendiente deben cubrir esa carrera. No se declara aún el objetivo
p99 de revocación ni el objetivo de latencia del hot path.

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

User y match usan vendoring generado según [ADR-008](ADR-008-private-go-dependencies.md).
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

Es un preview de **reservas**, no un control completo de la plataforma. Publicar
perfil, disponibilidad, mensajes, reseñas, catálogo/medios y otras superficies
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
- Configuración dev/qa/prd, Prometheus/promtool y diez reglas de alertas válidas.

La ejecución remota [39956656284](https://github.com/cazocarma/rac-infra-docker/actions/runs/39956656284)
pasó los cuatro jobs (incluida integración) con el commit anterior eceed7a. Esa
evidencia confirma la corrección V022 y la base previa, no los workers V023
añadidos después; estos tienen las pruebas locales anteriores y un nuevo CI al
publicar esta revisión.

## Pendiente para completar P03

1. Verificar Actions con estas revisiones y completar el rollout del enforcement,
   que sigue desactivado en el DEV existente.
2. Conectar la autoridad al ingreso autenticado de staff y a políticas aprobadas;
   consumidores de otros dueños y reconciliación.
3. Integración de todos los escritores y contrapartes, catálogo y medios,
   invalidación/reconciliación, controles al commit restantes y aviso en Flutter.
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
