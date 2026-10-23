# P03 — Estado de cuenta (en desarrollo)

D02 y D03 fueron confirmadas por el usuario el 22 de octubre de 2026.
La matriz y el alcance del cupo están en [ADR-001](ADR-001-standing.md).

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
concreta todavía no está conectada. El resultado no sustituye el control de
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
devuelve errores opacos. El publicador y los consumidores aún no están conectados.
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

1. El checkout de rac-platform y la base integrada ya pasaron en Actions. Falta
   conectar el módulo a los builds de servicios sin secretos en capas Docker ni `replace`
   local permanente.
2. Conectar la autoridad al ingreso autenticado de staff y a políticas aprobadas;
   transporte autenticado de consultas, consumidores de otros dueños y reconciliación.
3. Integración de todos los escritores y contrapartes, catálogo y medios,
   invalidación/reconciliación, controles al commit y aviso en Flutter.
4. Conectar los efectos pendientes de revisión al módulo de casos y probar
   integración de los workers con los controles autoritativos concurrentes.
5. Pruebas E2E con JWT anterior, particiones, dos instancias y carreras, además
   de medición de latencia bajo carga definida.

No hay enforcement nuevo activo en las APIs ni migraciones P03 aplicadas a DEV.
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
Estas son pruebas de transporte con identidad técnica de fixture, no una prueba
de JWT real ni de endpoints de negocio. Falta provisionar clientes con audience
y rol mínimos, conectar su verificador OIDC y enlazar las APIs.

El usuario autorizó añadir únicamente rac-platform a la App RAC CI Read con
Contents de lectura. La instalación se guardó y verificó con ocho repositorios seleccionados,
conservando los siete existentes y acceso de lectura a código/metadatos. El CI
integrado remoto 39956656284 pasó con el nuevo acceso.
