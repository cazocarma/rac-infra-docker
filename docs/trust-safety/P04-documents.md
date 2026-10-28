# P04 — Documentos y aceptaciones (en desarrollo)

## Estado actual

Registro y linaje inmutables, consentimiento exacto y control transaccional
implementados en user, reservas/agendas y envíos nuevos de chat. Los servicios
usan platform v0.13.0 en las ramas locales (aún sin push de este conjunto); match/chat leen datos documentales por la autoridad HTTP
con credencial técnica y solo bloquean metadata de coordinación en PostgreSQL.
La garantía de confirmación depende de la base compartida actual, descrita en
[ADR-010](ADR-010-document-coordination.md).

No habilitado en el DEV persistente. P04 no está cerrado: quedan publicación
humana aprobada, otros caminos de contenido público, integración web de los
otros dueños y rollout coordinado. El recorrido desktop de documentos,
cuestionario e historial se probó conectado en el laboratorio descrito abajo. El historial siguiente conserva
los avances y los pendientes que existían en cada incremento.

## Primer incremento

Rama independiente `feat/versioned-documents`, posterior al cierre de código de
P03. No declara P04 completo ni activa obligaciones sobre los usuarios.

V028 crea documentos versionados por tipo/idioma y aceptaciones por usuario y
documento. El contenido tiene SHA256 generado en PostgreSQL. Cambiar identidad,
versión o texto se rechaza; una publicación es inmutable. Un borrador puede
recibir metadata de revisión/publicación sin cambiar el contenido. No hay
semillas jurídicas ni API pública o comercial para aprobar/publicar documentos.
Los permisos de runtime son SELECT sobre documentos y SELECT/INSERT sobre
aceptaciones, sin UPDATE/DELETE ni permisos de publicación.

User ofrece:

- `GET /documents?locale=es`: última versión revisada/publicada por tipo, sin
  datos de aceptación. Borradores y publicaciones futuras quedan excluidos.
- `GET /documents/:id`: texto plano y hash de una versión exacta publicada.
- `GET /me/documents`: metadata publicada y fecha de aceptación de esa versión
  para la identidad autenticada, sin historial de otras personas.
- `POST /me/documents/acceptances`: lote atómico de una a cinco versiones con
  hash exacto, contexto enumerado y cuerpo acotado. El servidor decide sujeto y
  fecha. Un hash distinto o versión no disponible devuelve 409 y revierte el
  lote. Reintentar conserva la fecha/contexto originales.

Leer información propia y expresar aceptación son acciones de protección de
cuenta: no dependen de capacidades comerciales. No se almacenan IP ni user-agent
en este endpoint. Una lista vacía no significa que los textos estén aprobados ni
que un requisito de aceptación esté satisfecho.

Flutter agrega «Documentos y acuerdos» en Configuración. Lista versiones,
muestra texto sin interpretar HTML y exige marcar una casilla inicialmente
vacía antes de confirmar. El contenido y hash deben corresponder a la versión
abierta. Un conflicto retira el consentimiento local y exige actualizar la
lista; no acepta silenciosamente otro texto. Sin documentos revisados muestra
«En construcción». No hay intersticial obligatorio todavía.

## Verificación y siguientes incrementos

Las suites locales de Go con race y PostgreSQL migrado prueban hashes, ocultación
de borradores/futuro, rollback de lote, reintentos concurrentes, permisos negativos
y privacidad de la fecha de aceptación. Se usa una conexión real del rol
`rac_user`, no una sesión de superusuario con SET ROLE. El contrato OpenAPI 3.1
valida y sus cuatro tests existentes pasan. Flutter verifica anchos 360/1200,
consentimiento explícito, ausencia de texto definitivo cuando está vacío y
conflictos de versión. Flutter analyze pasa sin observaciones, las 47 pruebas
pasan y el build web release también. La suite de permisos fresh/upgrade y
backup/restore pasa con V028 y migrador sin superusuario.

P04 aún requiere la política compartida `RequireAcceptedDocuments`, gate 428
consistente en todos los escritores cubiertos, reaceptación por cambios
materiales, intersticial, declaraciones/cuestionario de compa, historial paginado,
ARB y metadata de revisión, flujos de publicación aprobados/auditados y pruebas
web conectadas. No usar estos endpoints para eludir standing o conceder roles.
La aprobación jurídica de textos y su activación siguen pendientes de sus
responsables; no se simulan mediante documentos de ejemplo en el DEV real.

## Segundo incremento: reglas compartidas (en integración)

`rac-platform` incorpora `documents.RequireAcceptedDocuments` en la rama
`feat/versioned-documents` (`60edab6`). Reutiliza la clasificación de capacidades
protectivas/comerciales de standing, sin copiar sus listas en cada servicio.
Distingue registro/política indisponible de aceptaciones pendientes y rechaza
registros vacíos, ambiguos, no revisados o futuros. Una nueva revisión no material
conserva su linaje de aceptación; un cambio material crea uno nuevo y exige
reaceptar. No hay bypass por rol administrativo: la persona documental se deriva
del dueño según perfil/operación, no de un rol de staff enviado por el cliente.

Vet y race de todos los paquetes del módulo pasan, incluyendo escenarios de
cambio material, hash alterado, consentimiento futuro/prepublicación y derechos
protectores con estado documental ausente. Esto prueba el evaluador de dominio,
no un middleware desplegado ni una lectura fresca entre servicios.

Falta persistir/derivar el linaje aprobado y el registro activo, conectar la
fuente autoritativa con identidad/operación y frescura acotada, volver a verificar
antes de commits y efectos externos, publicar la versión del SDK con vendor
generado en sus consumidores y conectar la respuesta 428 al intersticial.
El manifiesto y los consumidores siguen en platform v0.9.1 hasta esa integración;
no se edita vendor manualmente ni se declara el gate activo por compilar.


## Tercer incremento: registro autoritativo y linaje

V029 agrega un registro por idioma con versiones monotónicas, requisitos y
linajes inmutables. La activación exige un conjunto completo de documentos
aprobados y publicados, controla la versión esperada y registra el evento en
la cadena de auditoría dentro de la misma transacción. Repetir el mismo evento
no duplica auditoría ni retrocede el registro; cambiar su contenido se rechaza.

El linaje incluye las publicaciones históricas: una revisión material intermedia
obliga a reaceptar aunque no haya sido seleccionada como versión activa. Las
revisiones no materiales conservan el linaje previo. Se rechazan regresiones,
historias ambiguas y publicaciones retroactivas que alterarían un linaje ya
fijado. La función bloquea las escrituras de publicación antes de tomar el
bloqueo de la cabecera; un futuro ingreso de publicación debe conservar ese
orden para evitar carreras e interbloqueos.

Los servicios no pueden activar ni editar el registro. El usuario técnico de
lectura obtiene solo las columnas necesarias; los respaldos incluyen el esquema.
El bootstrap reconcilia su propietario con el migrador sin superusuario.
Las pruebas usan bases desechables y documentos sintéticos. No se ha activado
ningún documento ni aplicado esta migración al DEV persistente.

La función es una primitiva de persistencia, no el flujo humano de publicación:
los identificadores de aprobación todavía deben ligarse a una decisión
verificada mediante ese flujo. También siguen pendientes la fuente fresca del
SDK, los controles anteriores al commit y la respuesta 428 compartida.

Validación: `test_database_permissions.py` pasa tanto en instalación nueva como
en actualización desde V018, ejecutando las activaciones con el migrador real
sin superusuario. Incluye las pruebas negativas, el dump y la restauración.


## Cuarto incremento: comprobación fresca ligada a la operación

Platform `54a5da3` agrega `documents.Check` y el contrato `Source`.
La observación debe corresponder exactamente a cuenta, persona, capacidad e
idioma, y declarar una revisión positiva. El propietario construye esa consulta
a partir de la operación autenticada; no se deserializa del cuerpo público.
La tolerancia de antigüedad debe ser positiva y nunca superar cinco segundos;
se rechazan respuestas futuras, llamadas lentas, canceladas o fallidas.
No hay caché ni permiso reutilizable en esta comprobación. Los derechos
protectores no consultan la fuente documental.

Vet y race de todo platform pasan; la suite documental adicional verifica que
una segunda comprobación consulta de nuevo y rechaza un nuevo requisito material,
y que no se consulta la autoridad con contexto cancelado o tolerancia inválida.
Esto define y verifica el contrato compartido: todavía falta implementar la
fuente autenticada/consistente y coordinar la comprobación final con la
transacción del propietario. No elimina por sí solo una carrera entre lectura
y commit. El SDK no está publicado ni integrado en consumidores todavía.


## Quinto incremento: fuente PostgreSQL del propietario

Platform `e9aed5b` implementa `documents/postgres.Source`. Una única sentencia
lee la cabecera activa, su política, documentos, linajes y aceptaciones del
usuario resuelto por el subject OIDC. No sustituye un registro sin activar por
la publicación más reciente. La consulta devuelve solo una prueba por tipo
requerido que coincida con el linaje activo; no arrastra todo el historial de
aceptaciones a cada comprobación. Los errores internos se convierten en fallo
opaco y nunca se usan para conceder acceso.

`python scripts/test_document_source.py` ejecuta la SQL exacta extraída del
checkout hermano `rac-platform` contra PostgreSQL desechable migrado. Pasa con
`rac_user`, comprobando versión activa, cuenta inexistente, aislamiento entre
usuarios, hashes, herencia histórica no material y reducción de múltiples
aceptaciones. La prueba falla si falta esa fuente; no omite silenciosamente el
caso. Vet y race de platform/documentos también pasan con el nuevo adaptador.

La fuente está implementada pero aún no consumida: siguen pendientes transporte
autenticado, generación de vendor del SDK, coordinación con escrituras,
alineación de la lista pública con el registro activo y gate/intersticial 428.
El script debe incorporarse al CI cuando su checkout de platform esté fijado a
una versión que incluya esta fuente; aún no se afirma cobertura remota.


## Sexto incremento: transporte interno autenticado

Platform `832da41` agrega cliente y handler `documents/transport` con autenticador
obligatorio, consultas comerciales validadas, respuestas ligadas a la consulta,
JSON estricto, límite de 16 KiB y errores opacos. El cliente exige HTTPS salvo
la opción explícita de desarrollo y nunca sigue redirecciones. La vigencia se
comprueba mediante `documents.Check`; recibir una respuesta no concede por sí
solo un permiso reutilizable. El listener del propietario debe verificar la
identidad técnica, audiencia y permiso de lectura antes de consultar la fuente.

El intercambio HTTP acotado se comparte con standing mediante un paquete
interno; no se duplican sus reglas de credenciales, redirección y decodificación.
Vet y race de todo platform pasan, incluyendo regresión de standing y sus
credenciales. Las nuevas pruebas cubren acceso no autenticado, cuenta/operación
ligada, respuesta vencida/futura, JSON desconocido o con datos adicionales,
respuesta excesiva, ausencia de registro, redirección y acceso protector sin
consulta. El handler aún no está montado en user ni el cliente en match/chat;
no se ha ampliado ningún permiso de la App de GitHub o del realm OIDC.


## Séptimo incremento: SDK publicado y autoridad conectada en user

La etiqueta inmutable platform `v0.10.0` corresponde a `832da4174294`.
Los cuatro consumidores actualizan go.mod/go.sum y vendor generado; la fuente
se compara con el checkout fijado mediante `check_go_vendor.py` (pasa).
`python scripts/vendor_platform.py v0.10.0` reproduce esa generación desde un
tag existente y un checkout limpio, sin montar credenciales Git privadas en
Docker. Usa un proxy local de ese módulo exacto y mantiene proxy/checksum
públicos para las dependencias públicas. No modifica vendor manualmente.

User monta `/internal/documents` en su listener interno cuando
`DOCUMENTS_ENFORCEMENT_ENABLED=true`. Exige infraestructura standing activa,
audiencia `rac-documents`, permiso `documents.read` y subject técnico ligado al
cliente autorizado. Solo match/chat están admitidos; ni alert ni un admin humano
obtienen ese acceso. La configuración inválida aborta el inicio. La opción está
apagada por defecto y no se ha aplicado al DEV persistente.

Vet y race pasan en user, match, chat y alert. Las pruebas con JWT firmados
comprueban que el permiso/audiencia de standing no basta para documentos y que
el listener aplica esa separación. La suite normal omite sus casos PostgreSQL
sin fixture; no se presenta este resultado como una prueba integrada completa.
El manifiesto fija los cinco commits y el workflow integrado incorpora
`test_document_source.py`, ahora que el checkout de platform contiene la fuente.

Todavía falta provisionar esa audiencia/permiso en el realm desechable y validar
su token real, conectar los clientes de match/chat y los escritores locales,
coordinar el control antes de commit, y terminar el flujo 428/intersticial.
Publicar el SDK no activa ni completa P04 por sí solo.


## Octavo incremento: identidad documental probada en Keycloak

El provisionador standing acepta una opción documental explícita (desactivada
por defecto). Crea el recurso bearer-only `rac-documents` y el permiso
`documents.read`, asignados y limitados por scope solo a match/chat; alert
conserva exclusivamente standing. Se reutilizan los secretos montados actuales,
sin rotación implícita ni permisos realm-management. Reconciliar elimina los
permisos directos ajenos al conjunto aprobado. Se conservan los nombres de
mappers standing para actualizar instalaciones existentes.

`configure_identity.py` valida la opción documental antes de mutaciones:
requiere `DOCUMENTS_ENFORCEMENT_ENABLED=true` y standing activo. Todavía no hay
un overlay documental habilitado en Compose; no se ejecutó el provisionador
contra el realm DEV persistente.

`test_identity_permissions.py` pasa contra Keycloak desechable con TLS: dos
reconciliaciones con documentos conservan subjects/secretos, tokens reales de
match/chat incluyen audiencia y permiso, alert queda excluido y sigue sin
administración. Go verifica firma/issuer/audiencia/subject y deniega tanto un
token previo solo-standing como el de alert. La credencial OAuth real completa
intercambios con las autoridades standing y documental. Al deshabilitar la
opción, los tokens nuevos pierden documentos y conservan standing; los JWT ya
emitidos tienen su vencimiento corto habitual, no revocación instantánea por
quitar un mapper. El listener debe apagarse junto con ese rollout.

Pasan también las regresiones FGAP, denegación de privilegios, OTP/PKCE y MFA de
staff. El siguiente pendiente funcional sigue siendo aplicar el control en
escritores y conectar la experiencia 428; esta prueba no los sustituye.


## Noveno incremento: controles HTTP y confirmación transaccional en user

Platform `v0.11.0` (`9b3262f4a733`) agrega la respuesta compartida 428
`DOCUMENT_ACCEPTANCE_REQUIRED` (IDs inmutables, tipos, hashes y linaje pendientes)
y `documents/postgres.CheckLocked`. V030 concede a user una función mínima
`documents.lock_head`: mantiene un bloqueo compartido de la cabecera hasta
commit/rollback sin conceder UPDATE sobre el registro. Una activación toma el
bloqueo exclusivo y se serializa con esas escrituras. No se usa un bloqueo
autocommit ni se promete esa garantía para escritores remotos todavía.

Con la opción documental activa, user comprueba la aceptación antes de guardar
el perfil compa, publicar por el endpoint legado, editar habilidades o escribir
una reseña. La persona documental depende de la operación; admin no salta el
control. La comprobación final se realiza dentro de la transacción, antes de
asignar el rol compa externo y antes de confirmar; habilidades comprueba también
al propietario si un admin edita un perfil ajeno. El repo recibe explícitamente
la transacción en su callback. Lectura del perfil propio y aceptación siguen
accesibles; el idioma del control es es, fijado por el producto actual, no por
un parámetro público que pudiera escoger una política más permisiva.

Validación local:

- Vet y race pasan en platform y los cuatro consumidores con vendor generado.
- `test_migrations.py --services user` pasa: la base separada document_writes
  prueba 428, consentimiento por HTTP, publicación real con rac_user y cambio
  material entre preflight y escritura. La comprobación final revierte el perfil
  antes de asignar un rol externo. También pasan migraciones, standing, sesiones,
  permisos de escrituras existentes, adopción legacy y detección de checksum.
- `test_document_source.py` observa una conexión real con la transacción abierta
  y el bloqueo adquirido; la mantiene hasta la liberación explícita, sin depender
  de una duración de sleep para competir. La activación vence sin auditoría ni
  revisión parcial, y el mismo evento puede reintentarse tras liberar el lector.
- `test_database_permissions.py` pasa fresh y actualización V018: migrador sin
  superusuario, propietario de la función reconciliado, acceso exclusivo de user,
  negativas para otros servicios/backup y respaldo/restauración.
- OpenAPI valida y sus cuatro pruebas pasan; los cuatro escritores user declaran
  el 428. Estas validaciones locales no acreditan aún el CI remoto del nuevo head.

No está activo en el DEV persistente. P04 permanece abierto: faltan escritores
match/chat y su coordinación, otros caminos que puedan cambiar contenido público,
alinear la lista servida al registro activo, intersticial/ARB, declaraciones y
cuestionario compa, historial y el ingreso humano aprobado de publicación.


## Décimo incremento: reservas, agendas y chat coordinados

Platform v0.12.0 (`d943c4e1de48`) añade comprobación remota bajo bloqueo y el
constructor de cliente técnico con secreto montado. V031 concede a user/match/chat
solo `documents.lock_registry`; devuelve revisión y referencia de política bajo
bloqueo compartido y no concede SELECT de tablas documentales a match/chat.
El SDK exige que la autoridad autenticada responda esa misma revisión/política,
con identidad, persona, operación, idioma y frescura correctos. Ver ADR-010 para
la dependencia explícita de la base compartida, sin prometer un lock distribuido.

Match comprueba al comprador para crear/extender reservas y al compa para
aceptarlas. Agendas y ausencias comprueban propietario y actor cuando difieren.
Hay preflight y control final dentro de la transacción. Se reutiliza una única
instancia configurada del repositorio también en ausencias; no se construye un
segundo repositorio que omita sus controles. Las cancelaciones y lecturas propias
no consultan la autoridad documental.

Chat deriva la persona de la relación en la reserva, nunca del rol admin del
JWT. Un envío nuevo comprueba antes de insertar y antes de confirmar su mensaje
y outbox. El replay idéntico de un envío ya confirmado devuelve el resultado
original sin crear efectos ni exigir aceptación nueva; no es un nuevo envío.
Historia, seguridad y bloqueo siguen disponibles si documentos está caído.

Evidencia local del incremento:

- Vet y race de platform y los cuatro consumidores pasan; vendor generado
  coincide con el SDK fijado y todos usan v0.12.0.
- `test_document_source.py` prueba el bloqueo real con cada rol user/match/chat,
  observa la transacción abierta, fuerza timeout de activación sin efectos
  parciales y reintenta el mismo evento tras liberar el escritor.
- `test_database_permissions.py` pasa fresh/upgrade V018 con migrador sin
  superusuario, propietario correcto de la función, negativas de lectura
  documental en match/chat, exclusión de alert/backup y respaldo/restauración.
- `test_migrations.py` completo pasa (user/match/chat). Las bases aisladas
  document_match y document_chat verifican HTTP con autoridad privada real en
  rol rac_user, escritores rac_match/rac_chat, aceptación por persona, cupo,
  cambio material entre preflight/commit, reversión de reservas/mensajes/outbox,
  política discordante, outage y acceso protector/reintentos sin nuevo efecto.
  El bearer de estos fixtures es sintético y se valida en el handler; firma,
  issuer y audiencia se verifican en la suite Keycloak del octavo incremento.
  También pasan las regresiones P03, recuperación sin broker, sesiones,
  migraciones legacy, repetibilidad y detección de checksum.
- OpenAPI valida y pasan sus cuatro pruebas; los escritores match y el envío
  privado declaran el 428 compartido. No se afirma todavía CI remoto del head.

No se ha agregado el overlay de activación ni ejecutado estas migraciones sobre
el DEV persistente. El siguiente trabajo es la lista autoritativa y la experiencia
web/mobile de aceptación, manteniendo los pendientes de publicación y revisión
humana del plan completo.


## Registro activo en API y aplicación

La lista de documentos con enforcement habilitado procede del conjunto activo,
no de la última publicación de cada tipo. Devuelve referencia de idioma,
revisión y política, con un máximo de tres puntos de resumen revisados. Una
publicación que todavía no pertenece al conjunto activo no cambia la lista.
Un idioma sin registro activo devuelve indisponibilidad, sin fallback implícito.

La aceptación envía la referencia del registro junto al ID y hash exactos del
texto que se leyó. El servidor bloquea el registro durante la transacción y
rechaza referencias ausentes o antiguas con 409; no guarda consentimiento parcial.
Flutter conserva la referencia al abrir el lector y pide actualizar la lista si
cambió el registro. No preselecciona aceptación ni acepta versiones nuevas por
herencia del consentimiento anterior.

Verificación local: Go vet/race, migraciones de usuario con escenarios de cambio
concurrente y publicación no activa; Flutter analyze, 49 pruebas y build web;
OpenAPI validado y cuatro pruebas de contrato. Este incremento todavía no
implementa el intersticial global, ni activa enforcement en DEV. Los commits de
API, aplicación y contrato permanecen locales mientras corre la corrección de CI.


## Transporte del intersticial (trabajo local)

El transporte JSON común reconoce únicamente 428 con el código documental y un
conjunto no vacío de hasta cinco identidades válidas y únicas. Conserva ID,
tipo, hash y linaje; no conserva el cuerpo del mensaje, reserva o pago rechazado.
Emite una notificación efímera y mantiene el error original para la pantalla que
inició la operación. No refresca sesión por 428 y no repite la escritura.

Pendiente conectar la presentación S2 y los clientes HTTP propios de MatchApi y
UserApi. Esta base de transporte no implica cobertura global ni cierre del gate
web. La prueba local cubre rechazo de metadata malformada/duplicada y ausencia
de reenvío automático. Flutter analyze y las 51 pruebas de la suite pasaron
localmente después de corregir una fixture de prueba con tipo incompatible.


## Clientes HTTP anteriores conectados

MatchApi, UserApi y CompaApi usan un observador del transporte HTTP que conserva
bytes, estado y cabeceras de la respuesta. Solo inspecciona respuestas 428, con
un máximo de 16 KiB de metadata acumulada; cuerpos mayores o JSON inválido no
generan avisos ni cambian el error original. No retiene solicitudes ni altera
los reintentos existentes de los consumidores. El cierre del cliente sigue
cerrando el transporte subyacente.

Flutter analyze y 52 pruebas pasaron localmente, incluyendo respuestas válidas,
malformadas y superiores al límite con comparación del cuerpo original y una
única solicitud. Falta conectar la interfaz S2 y comprobarla en navegador;
conectar el transporte no constituye la aceptación del usuario.


## S2 y localización de interfaz (implementación local)

La raíz de Flutter escucha las precondiciones de todos los transportes conectados
con una única suscripción y evita abrir pantallas simultáneas. S2 consulta el
registro activo y comprueba que cada ID, tipo y hash pendiente siga en ese
conjunto; si cambió, pide volver a la acción original. No deduce la persona
cliente/compa del rol admin y no acepta documentos adicionales por inferencia.

Muestra hasta tres puntos del resumen del registro y enlaces a los textos
completos. Comprueba identidad y hash del detalle antes de habilitar la marca de
lectura. La casilla de consentimiento comienza desmarcada; tras revisar todos
los textos, el usuario puede aceptar el lote exacto con la referencia del
registro. El backend conserva atomicidad. Un 409 borra la selección e impide
reintentar con una referencia antigua. Cerrar o completar S2 nunca repite la
reserva, mensaje o pago original.

Los textos nuevos de interfaz están en ARB español/inglés, con flutter gen-l10n,
configuración versionada y salidas generadas. No se traducen ni publican términos
legales por este mecanismo: los textos documentales siguen viniendo de la
versión revisada del servidor, actualmente idioma español.

La salida a datos/derechos es accesible sin marcar consentimiento y permite ir
al perfil. La pantalla declara expresamente que exportación y eliminación están
en construcción y que no se envió ninguna solicitud. El workflow de derechos
sigue pendiente de P12; este enlace no demuestra que ya esté implementado.

Evidencia local: análisis sin incidencias, suite completa de 56 pruebas aprobada,
siete pruebas focalizadas de S2 aprobadas (tres casos añadidos después de la
suite) y build web release correcto. Casos: 360/1200 px, casilla desmarcada,
lectura exacta, lote con referencia, hash distinto, conflicto, deduplicación y
cancelación de suscripción, salida de derechos sin aceptación. Pendiente prueba
en navegador con backend conectado, revisión visual y activación coordinada.
No se activaron obligaciones sobre usuarios DEV ni se enviaron estos commits.


## Reglas de declaraciones y cuestionario (núcleo local)

`rac-user-service/internal/attestations` valida una definición revisada de cinco
declaraciones independientes y tres preguntas de situación, con 2–4 opciones por
pregunta. Las cinco identidades corresponden a sustancias ilícitas, servicios
sexuales, catálogo, mayoría de edad y actuación/apelación. No contiene textos
jurídicos definitivos ni definiciones activas: las pruebas usan texto sintético.

La definición se vincula a revisión del registro documental y política, idioma,
versión, hash de contenido y autor/fechas de revisión y publicación. La aprobación
es información confiable que debe proveer el dueño, nunca una afirmación del
cliente. Se rechazan borradores, publicaciones futuras, claves/IDs duplicados,
respuestas correctas inexistentes, texto inválido y cambios de contenido.
El digest usa JSON de las estructuras Go, con orden de campos definido y orden
de arreglos preservado; cualquier adaptador de persistencia/publicación debe
conservar ese contrato, sin sustituirlo por otro serializador JSON implícito.

El intento exige exactamente las cinco marcas verdaderas y las tres respuestas
correctas para la versión/hash indicados. Una marca ausente o falsa y campos
adicionales no equivalen a consentimiento. La vista pública excluye la clave de
respuestas por estructura y copia sus arreglos para evitar alias mutables.
El resultado no verifica identidad, no acepta documentos, no aprueba un listing,
no concede un rol y no sanciona intentos fallidos.

Pendiente: persistencia de definiciones/intentos aprobados con idempotencia,
API autenticada, referencia vigente bloqueada en la transacción de publicación,
contratos, asistente Flutter y pruebas conectadas. El paquete puro por sí solo
no impide saltarse el onboarding y no cierra el requisito de declaraciones.

Verificación del núcleo: `go vet ./...` y `go test -race -count=1 ./...`
aprobados en user con Go 1.27.2. Las pruebas PostgreSQL que requieren fixtures
no se ejecutan en este comando sin sus variables; esto no prueba persistencia
de declaraciones ni cierre transaccional del onboarding.


## Persistencia y API de declaraciones (V032, local)

V032 agrega definiciones con contenido/hash inmutable, revisión y publicación;
bindings inmutables por registro documental; y aprobaciones propias por usuario
y definición. No inserta cuestionarios ni bindings. Runtime puede leer y
registrar aprobaciones, sin publicar, aprobar, modificar ni borrar estos datos.
La supresión futura queda reservada al workflow revisado de derechos/retención:
no se agregó un trigger que impida el borrado del sujeto por cascada.

`GET /me/compa/attestation?locale=es|en` devuelve únicamente la definición
revisada vinculada al registro activo, sin clave de soluciones, y la fecha de
primera aprobación de la identidad autenticada. Un binding ausente o borrador
produce 503. `POST` recibe versión, hash, referencia del registro, cinco marcas
y tres respuestas. Rechaza propiedades desconocidas/duplicadas, JSON adicional,
exceso de cuerpo (8 KiB), referencias antiguas y respuestas incorrectas. El
sujeto, la definición y la fecha son determinados por el servidor.

La transacción toma el lease del registro documental y registra solo intentos
correctos. Ocho solicitudes concurrentes y sus reintentos conservan una fila y
la primera fecha. Un binding no material puede reutilizar la misma definición
y aprobación; enviar una referencia antigua sigue devolviendo 409. La operación
no concede roles, no acepta documentos y no aprueba ni publica perfiles.

Evidencia local: Go vet y race de user; suite de migraciones con fixture propia
`attestations`; ocho envíos concurrentes, privacidad por sujeto, permisos
negativos, versión inmutable y activación concurrente detenida por el lease;
actualización desde V018 con migrador no superusuario y dump/restore con rol
backup; OpenAPI validado y seis pruebas de contrato. La fixture usa únicamente
contenido sintético y nunca la base DEV. El driver exige el PASS explícito de
`TestCompaAttestationsPostgres` cuando el repo contiene esa prueba.

Pendiente de este requisito: asistente Flutter de cinco casillas/tres preguntas,
enforcement final dentro de todos los caminos de publicación, publicación humana
aprobada y pruebas de navegador. No se activó V032 sobre el DEV persistente ni
se enviaron estos commits a remoto durante la CI anterior.


## Asistente Flutter de declaraciones y cuestionario

`/compa-rules`, protegido por autenticación y accesible desde Sé Compa, carga
la definición revisada de la API propia. Presenta cinco casillas independientes
inicialmente desmarcadas y tres preguntas sin alternativa elegida. El cliente
no incorpora soluciones ni califica: el servidor valida las tres respuestas.
El modelo rechaza definiciones incompletas/duplicadas, referencias inválidas y
respuestas que contengan una clave `correct_option` expuesta por error.

Confirmar envía versión, hash, referencia del registro y selecciones, sin sujeto,
fechas ni flags de aprobación. Una respuesta incorrecta o fallo transitorio
conserva lo editado para corregir/reintentar; un 409 borra todas las selecciones,
inhabilita el envío y exige cargar nuevamente. Una aprobación ya existente se
muestra como tal, sin enviar otro intento automáticamente. El éxito no publica
el perfil ni concede permisos. Se conserva la salida de datos/derechos.

Las etiquetas de interfaz nuevas están en ARB es/en; las declaraciones y
situaciones se muestran tal como fueron revisadas por el servidor (locale es).
Si no hay definición aprobada o no se puede cargar, muestra indisponibilidad y
reintento sin inventar declaraciones, soluciones o un estado de aprobación.

Verificación local: analyze limpio, 65 pruebas Flutter y build web release.
Casos nuevos: envío acotado a los campos de contrato, definición inválida,
casillas/radios vacíos y envío correcto en 360/1200 px, corrección tras 422,
reinicio por 409 e indisponibilidad. Pendiente navegador conectado y enforcement
transaccional de todos los writers. El formulario de publicación actual aún no
exige este paso; no presentar este avance como un bloqueo completo del bypass.


## Exigencia final de cuestionario en publicación y notificación a Flutter

Con `DOCUMENTS_ENFORCEMENT_ENABLED=true`, el chequeo transaccional de publicación
compa exige también una aprobación correcta de la definición revisada actualmente
vinculada al registro. Se aplica a PUT del perfil propio, POST legacy de compas
y reemplazo de habilidades, mediante el mismo chequeo final que ya usaban esos
writers. No se agregó una bandera alternativa que permita encender documentos
y omitir declaraciones. El control ocurre antes de asignar el rol externo y se
mantiene el lease del registro hasta confirmar/revertir la escritura.

Una aprobación ausente devuelve 428 `COMPA_ATTESTATION_REQUIRED`; una definición
no disponible o una aprobación almacenada inconsistente devuelve 503. La revisión
lee y valida las marcas/respuestas almacenadas, no solo la existencia de una fila.
Un nuevo binding puede reutilizar una definición inmutable ya aprobada, pero una
definición nueva requiere completar su propio cuestionario. Cancelar reservas,
leer datos, reportar, aceptar documentos y presentar el cuestionario no dependen
de esta exigencia de publicación.

Para la edición de habilidades por staff se comprueban actor y dueño. Si faltan
obligaciones documentales o de cuestionario del dueño, devuelve 409
`owner_prerequisites_required`, sin pedir al actor que acepte en su nombre.
Las indisponibilidades no se transforman en autorización ni en aprobación.

Flutter reconoce el nuevo 428 en ambos transportes y abre una única pantalla de
cuestionario, compartiendo la exclusión de pantallas simultáneas con S2. La
notificación no contiene el cuerpo de la operación ni produce reenvío automático.
El usuario vuelve a intentar la publicación después de completar el requisito.

Verificación local: Go vet/race; fixture PostgreSQL de user con cambio de definición
entre preflight y commit, rollback de perfil/habilidades, bloqueo antes de grant,
no bypass de admin y caso actor/dueño; migraciones frescas/legacy/repetidas/checksum;
Flutter analyze, 67 pruebas y build web; OpenAPI y siete pruebas de contrato.
No se aplicó a DEV persistente ni se envió este incremento. Pendiente navegador
conectado, publicación humana y rollout; los otros writers de contenido público
fuera de estas tres rutas siguen en la revisión general de P04/P08.


## Historial propio de aceptaciones (V033 y Flutter)

`GET /me/documents/history` devuelve versiones históricas exactas, hash, fecha y
contexto originales. La identidad procede únicamente del token; no selecciona
cuentas por parámetros. No depende de standing comercial ni de un registro
activo, no expone contenido completo ni acepta documentos. Respuestas no-store.

Paginación descendente por `(accepted_at, document_id)`, límite 20 por defecto y
1–50 permitido, cursor versionado/base64url de hasta 512 caracteres y sin valor
de autorización. La consulta siempre vuelve a limitar al sujeto autenticado.
Rechaza límites/cursors duplicados o inválidos. V033 agrega un índice por usuario,
fecha e identificador. Las nuevas aceptaciones pueden requerir recargar la primera
página: no se presenta como un export consistente a un instante.

Flutter ofrece Historial desde el encabezado de Documentos, incluso cuando no
se puede cargar el registro actual. Muestra fecha local con zona y contexto,
permite cargar más conservando filas anteriores ante fallos y abre el texto
histórico en el lector con aceptación ya registrada, sin casilla ni envío nuevo.
Las etiquetas nuevas están en ARB es/en. No inventa aceptación de una versión
nueva a partir de una firma anterior o de su linaje no material.

Verificación local: Go vet/race, fixture PostgreSQL con tres aceptaciones de
igual timestamp paginadas de una en una, versiones ya no actuales, límites,
autenticación y cambio a otra identidad con cursor/usuario ajenos sin filas;
migraciones frescas/legacy/repetidas/checksum; Flutter analyze, 72 pruebas y build
web; OpenAPI y ocho pruebas de contrato. No se aplicó a DEV persistente ni se
publicaron estos commits. Falta la comprobación conectada en navegador.


## Laboratorio web conectado y regresiones encontradas

Se agregó [P04-browser-lab.md](P04-browser-lab.md), Compose y un runner con
credenciales generadas, puertos de loopback, PostgreSQL tmpfs y recursos con
prefijo aleatorio. No lee credenciales DEV ni combina su overlay. El validador
rechaza recursos persistentes, puertos públicos, escrituras de host e imágenes
DEV, y corre en `make test-workflows` antes de las suites costosas.

Recorrido real en el navegador integrado, 1280×720, con Keycloak/OIDC/PKCE,
backend auth/user, frontend compilado y PostgreSQL migrado hasta V033:

- Login sintético y bloqueo de publicación por cinco documentos. Casilla vacía,
  botón deshabilitado y escape a derechos accesible sin aceptar.
- Lectura de las cinco versiones y consentimiento explícito; no hubo reenvío
  automático de la publicación.
- Nuevo intento abrió cuestionario con cinco casillas/tres respuestas vacías.
  El servidor rechazó respuestas incorrectas y permitió corregirlas. Completar
  el paso no publicó el perfil; un intento explícito posterior sí lo publicó y
  el frontend verificó el rol compa tras refrescar la sesión.
- Un cambio material sintético activó únicamente privacidad v2. El formulario
  pidió esa versión nueva y conservó la aprobación del cuestionario inmutable.
  El historial mostró privacidad v1 y v2, y el lector histórico no ofreció una
  nueva aceptación.
- Conteos finales: seis aceptaciones, una aprobación de cuestionario, un perfil,
  registro documental 2 y esquema V033. No se crearon intentos fallidos como
  aprobaciones ni perfiles duplicados.

Se encontraron y corrigieron dos regresiones que los tests previos no mostraban:
SelectableText pintaba el texto completo sin exponerlo al árbol accesible web;
se agregó una etiqueta semántica completa manteniendo selección. Además, la URL
inicial de la plataforma podía generar rutas antes del gate de sesión y dejar
una puerta dormida debajo del inicio. Se construye una sola ruta bootstrap y
luego Home/ruta solicitada; se probó con `defaultRouteNameTestValue` y en navegador
tras recargar historial. Home quedó como raíz, sin un Atrás hacia una pantalla
vacía. La API de formulario también preserva el tipo 428 para no presentarlo como
un problema de conexión.

Analyze y 78 pruebas Flutter aprobados; Docker construyó y ejecutó la versión
corregida. La evidencia local está en `.local/p04-browser-proof/report.json`, con
revisiones, hashes del harness, capturas y conteos sanitizados. La limpieza fue
verificada: cero contenedores/redes/volúmenes del proyecto y RustFS original sano.
Las imágenes de build quedan como caché local; no contienen el env de la fixture.

Límites: recorrido conectado desktop manual; tamaños móviles siguen cubiertos
por widgets, no por este navegador. No inició match/chat/alert/pagos ni demuestra
los E2E del ecosistema completo. Las aprobaciones y textos fueron sintéticos;
no es una publicación jurídica definitiva ni un rollout de DEV persistente.


## Cambios de contenido del perfil público

Las rutas `PUT /me`, `PUT /me/photo` y el reemplazo heredado `POST /profile`
comprueban los documentos y el cuestionario de compa cuando el dueño ya tiene
un `compa_perfil`. La persona se deriva de esa relación persistida, no del rol
del JWT: un token antiguo con `cliente` no evita los requisitos. La lectura se
hace en la transacción de escritura y conserva el bloqueo compartido del
registro hasta el commit. Para fotos se adquiere antes de escribir el objeto.

`PUT /me` compara nombre, biografía e intereses bajo bloqueo de la fila: editar
solo contacto/localización sin cambiar esos campos públicos no agrega una
obligación documental. El reemplazo heredado sigue siendo una escritura completa
de perfil. La creación inicial sin perfil comercial no exige cuestionario;
eliminar la foto, consultar documentos y consultar datos propios mantienen sus
rutas protectoras. Los controles de standing existentes se conservan.

Esto cubre los campos que el catálogo toma directamente de `usuario`; no
sustituye la revisión/moderación de contenido de P08/P09 ni declara terminada
la publicación humana aprobada de documentos. La prueba PostgreSQL de guardas
incluye token con rol antiguo, rollback de ambos escritores de perfil, ausencia
de nuevos objetos en una carga rechazada, edición de contacto y eliminación de
foto con aceptación documental pendiente.


Verificación local de este incremento: `go vet -mod=vendor ./...` y
`go test -mod=vendor ./... -count=1` en Go 1.27.2; además
`python scripts/test_migrations.py --services user` completo (incluye la suite
HTTP con `-race` contra PostgreSQL migrado, bases fresh/legacy, repetibilidad y
deriva de checksums). El laboratorio copió los archivos actuales de producción
y de prueba; sus SHA256 coincidieron antes de ejecutar. Evidencia local:
`.local/p04-public-profile-go.log` y `.local/p04-public-profile-postgres.log`.
Los recursos desechables se retiraron al finalizar; DEV no se migró ni activó.


## Entrada autenticada para revisión humana (primer incremento)

Admin prepara un guard independiente para la consola con audiencia
`rac-admin-staff`, cliente autorizado `rac-staff`, roles de cliente y prueba
pwd+otp en AMR. Exige autenticación de menos de cinco minutos y tokens de cinco
minutos como máximo; refrescar no prolonga el MFA. El rol legal obtiene los
permisos documentales; los otros cuatro roles staff solo consultan su propia
sesión en esta etapa. Un admin de realm/app o un rol legal de otro cliente no
obtiene esos permisos. Matriz y configuración: `rac-admin-service/README.md`.

`STAFF_ACCESS_ENABLED` está apagado por defecto y no está incorporado a los
overlays. Solo se agrega una ruta de lectura de sesión; no se publican textos,
no hay conexión de admin a BD ni se otorgan grants de escritura. El cliente
Keycloak permanece deshabilitado: se agrega audiencia explícita, se elimina
fullScopeAllowed y se limita el scope a sus cinco roles propios, sin asignarlos
a personas. No se modifica DEV persistente durante estas pruebas.

Pasaron vet y race de admin, los nueve tests de contratos y el ensayo completo
`python scripts/test_identity_permissions.py` con Keycloak 26.8.1 y TLS en un
realm desechable. El ensayo verifica el token real con JWKS, issuer, audiencia,
azp, rol legal, AMR/frescura y la ruta HTTP de sesión; rechaza ID/service tokens,
prueba contraseña insuficiente y OTP+PKCE válido, comprueba que no hay permisos
administrativos y deja el cliente apagado. Archivos locales de evidencia:
`.local/p04-staff-access-go.log` y `.local/p04-staff-access-keycloak.log`.

Quedan los comandos de borrador/revisión/publicación con hash y versión
esperados, revisión humana atribuida y auditoría atómica; este incremento no
cierra ese pendiente ni P04. El enrolamiento real de staff y su activación
siguen dependiendo de D10.


## Ledger editorial y comandos transaccionales (verificado en laboratorio)

V034 agrega `documents.editorial_revision`, `editorial_review` y
`editorial_event`, inmutables. `draft_document` guarda un texto/hash exacto y su
autor; `review_document` exige un revisor distinto y registra aprobación o
rechazo sobre esa versión; `publish_document` solo publica la aprobación exacta.
Un rechazo es definitivo para ese borrador: corregirlo requiere otra versión,
no sobrescribir el texto revisado. Las fechas pertenecen al servidor. Una
publicación no activa automáticamente el registro ni liga un cuestionario.

Cada comando es idempotente por event_id y contenido exacto del comando
(incluidos actor/política/hash); reutilizar el evento con otros datos falla.
Comandos, metadata de revisión y append de auditoría comparten transacción:
si el escritor de auditoría no está configurado, no queda un borrador parcial ni
una publicación sin evento. Los comandos respetan el mismo orden de bloqueo del
prefijo documental que `documents.activate`. Se serializa este camino editorial
de baja frecuencia, sin cambiar el bloqueo compartido de las escrituras de app.

La cadena registra tres acciones explícitas: `document.drafted`,
`document.reviewed`, `document.published`. `actor_id` sigue siendo el principal
de servicio autenticado en PostgreSQL; el actor humano está en el ledger
propietario y se correlaciona por event_id. El comando guarda hash y metadata,
no duplica el texto ni incorpora tokens o datos de contacto en la cadena.
El enum se amplía en el módulo y contrato; el canónico RAC-AUDIT-1 no cambia.
Antes de habilitar el ingreso hay que publicar la siguiente versión del módulo
y actualizar sus verificadores/consumidores, que hoy siguen en v0.12.0.

Las funciones están cerradas: no reciben EXECUTE los roles de runtime, backup
ni PUBLIC; tampoco se crea un login editorial. No son por sí solas una prueba
de identidad humana: el futuro ingreso propietario debe verificar el token staff,
derivar actor/política del contexto autorizado y volver a comprobar su frescura
antes de commit. Admin no debe recibir grants sobre las tablas de user: enviará
comandos al dueño por su API interna. Faltan ese ingreso, la vinculación de
privilegios mínimos, el flujo del cuestionario y la activación revisada del
conjunto. No se declaran publicación humana completa ni cierre de P04.


Verificación de V034: suite completa de migraciones de user con race y casos
editoriales sobre PostgreSQL real, fresh/legacy/repetibilidad/checksums, y suite
de permisos fresh + upgrade desde V018 con Flyway no superusuario y
pg_dump/restore. El ensayo editorial reconstruye en Python los nueve hashes
encadenados, verifica el servicio y la atribución humana separada y prueba
replays/competencia entre revisores, rechazo, inmutabilidad y permisos negativos.
Pasaron vet/race de platform y diez pruebas de contratos. Evidencia local:
`.local/p04-editorial-postgres-recheck.log`, `.local/p04-editorial-permissions.log`
y `.local/p04-editorial-platform.log`. El primer intento reveló la codificación
implícita de subprocess en Windows; el ejecutor usa UTF-8 explícito y el caso
con texto español se conserva. Los recursos desechables se limpiaron; DEV no
se migró. No hay versión nueva del SDK publicada ni rollout editorial activado.


## Guard staff compartido y dependencia generada

La autenticación deja de estar duplicada en admin: `rac-platform/staff`
verifica firma, issuer, audiencia explícita por dueño, cliente, roles, MFA y
frescura; su middleware HTTP guarda la sesión verificada en contexto. Admin
conserva solo la configuración y el adaptador Gin. `Session.Check` comprueba otra
vez permiso y vencimiento antes de commit; renovar el token no renueva MFA.
`documents.publish` se distingue de la activación del registro. Hay pruebas de
que un token destinado solo a admin no sirve para la audiencia propietaria
`rac-user-documents`, y de vencimiento mientras se espera el almacenamiento.

El tag local inmutable v0.13.0 fija el guard y las acciones editoriales. Vendor
se genera con Go para user, match, chat, alert y ahora admin; el verificador de
fuentes incluye los cinco consumidores. El generador ejecuta tidy antes de
vendor para resolver las dependencias declaradas del módulo, sin modificar a
mano el árbol generado. Admin compila y ejecuta CI con vendor y proxy/sumdb
apagados; su imagen incorpora vendor y no descarga el módulo privado.
La prueba real de identidad también compila admin offline antes de obtener el
token corto. No se retaggeó v0.12.0 ni se publicó este conjunto todavía.

Este incremento no conecta por sí solo el listener editorial de user. Quedan
el ingreso propietario, la credencial de BD acotada, el proxy de consola y la
activación aprobada del conjunto/cuestionario. Staff y escrituras editoriales
siguen deshabilitados en DEV persistente.


Verificación del guard compartido: vet/race de los cinco consumidores con
GOPROXY/GOSUMDB apagados y contenedor sin red; guard de platform probado con
JWT RSA firmados, audiencias por dueño y vencimiento antes de commit; diez tests
de contratos y OpenAPI 3.1; integridad/tampering del vendor incluyendo admin;
actionlint de admin y `make test-workflows` de infra. La imagen de admin se
construyó con `--network=none`. El ensayo Keycloak real validó también un refresh:
el issuer conserva auth_time/AMR y el middleware verifica ambos access tokens
con el mismo límite MFA. ID/service tokens siguen denegados y el cliente staff
queda deshabilitado al terminar. Evidencias locales:
`.local/p04-shared-staff-platform.log`, `.local/p04-shared-staff-consumers.log`,
`.local/p04-shared-staff-keycloak-refresh.log`,
`.local/p04-shared-staff-admin-image.log`, `.local/p04-shared-staff-vendor.log`
y `.local/p04-shared-staff-workflows.log`. Docker Desktop se había detenido;
se recuperó el motor sin migrar ni levantar el stack DEV. Al final solo quedó
RustFS original saludable. El tag y los commits son locales, sin push ni
actualización todavía del manifiesto remoto de CI.


## Ingreso editorial propietario de user (verificado en laboratorio)

User agrega el listener interno 8083, apagado por defecto y sin rutas en su API
pública. Verifica el token staff con la audiencia propietaria rac-user-documents
y el guard común; rol legal, MFA y permiso se comprueban antes del comando y otra
vez antes del commit. Actor/política no son campos aceptados del navegador.
Implementa borrador/revisión/publicación idempotentes y lectura del texto/hash
exactos. Configuración y rutas detalladas: rac-user-service/README.md.

V035 agrega solo el lector y readiness del principal editorial, con ejecución
PUBLIC revocada. No crea login, grants de runtime ni contenidos. El listener
exige una conexión dedicada sin roles heredados, sin lectura/escritura de tablas
de negocio y sin ejecución de las primitivas audit/activación; requiere que su
escritor de auditoría ya esté provisionado. La lectura de catálogo/extensiones
no se confunde con acceso a tablas de negocio. Esperas de comandos tienen tope
de cinco segundos/fecha de MFA, y el límite de lock es dos segundos.

La configuración staff prepara también audiencia rac-user-documents; el cliente
sigue apagado y no se asignan roles a personas. El ensayo de Keycloak verifica
el access token real ante ambas autoridades y mantiene el MFA original tras un
refresh. El flujo editorial no requiere ni concede un perfil comercial/rol compa.

Las pruebas PostgreSQL usan un login real que solo recibe USAGE y EXECUTE de
cinco funciones, no SET ROLE desde una sesión superuser. Rechazan credenciales
amplias, resuelven los tres comandos con JWT firmados, leen la revisión exacta
aún no publicada y comprueban reintentos sin nueva auditoría. Una secuencia de
sondeo exclusivamente de la fixture acredita que el INSERT de auditoría sí
ocurrió antes de simular el vencimiento MFA: se revierten tanto evento como
borrador. Perder el principal de auditoría hace fallar readiness y el comando,
sin publicación parcial. Tokens/cuerpos/DSN no se incluyen en errores.

El parser JSON estricto es compartido por el ingreso y los consentimientos de
user; el wrapper HTTP anterior conserva su firma. Se rechazan también alias de
mayúsculas duplicados y UTF-8 inválido, sin reemplazarlo silenciosamente. El
límite y el hash se aplican a bytes UTF-8 del texto ya decodificado.

Siguen pendientes el proxy/consola, provisión aprobada del login editorial y
staff, cuestionarios revisados y activación atómica del conjunto. No se habilita
este listener ni se migra DEV persistente mediante estos ensayos. P04 sigue
abierto.


Verificación completada: vet y race de user; once pruebas de contratos y
OpenAPI 3.1; suite de migraciones completa con nuevo `TestEditorialPostgresHTTP`,
fresh/legacy/repetibilidad/checksum, rol restringido real y prueba de rollback
tras INSERT de auditoría; permisos fresh/upgrade desde V018 con migrador no
superusuario y dump/restore; Keycloak real para la audiencia propietaria y
refresh sin extender MFA; imagen user construida con red deshabilitada. El caso
de UTF-8 inválido conserva el resto del cuerpo válido y el hash que coincidiría
si el decoder reemplazara el byte: prueba que se rechaza, no se repara.
Evidencias locales: `.local/p04-editorial-ingress-go-final.log`,
`.local/p04-editorial-ingress-final-input.log`,
`.local/p04-editorial-ingress-postgres.log`,
`.local/p04-editorial-ingress-permissions.log`,
`.local/p04-editorial-ingress-keycloak.log`,
`.local/p04-editorial-ingress-image.log` y
`.local/p04-editorial-ingress-vendor.log`. Los recursos de ensayo se limpiaron.
Este conjunto permanece local y sin activación de DEV.


## Proxy de consola hacia el dueño documental

Admin incorpora el proxy de origen fijo, sin BD de user. Las rutas
/api/admin/staff/documents/drafts, reviews, publications y lectura por id se
registran solo con staff y proxy habilitados. El mismo token viaja al listener
editorial de user, que exige su propia audiencia y vuelve a imponer actor,
MFA, revisión/hash y commit. Contrato de entrada intacto; no se normalizan campos
ambiguos ni se conceden roles. Variables y detalles: rac-admin-service/README.md.

El transporte no sigue redirecciones, no toma destino/query/host de la solicitud,
no usa proxies de entorno y no reintenta escrituras. Solo envía bearer y tipo de
contenido, con cuerpo/límite de respuesta 1 MiB y RPC de cuatro segundos como
máximo, también acotado por la sesión. Respuestas se validan completas: id
esperado, texto/hash y campos previstos o error permitido. No expone HTML,
campos/diagnósticos extra, cookies o cabeceras de origen. El readiness del dueño
se integra cuando el proxy está activo, mediante un probe sin credenciales.

Una pérdida de respuesta no equivale a rollback. La consola conservará evento
y cuerpo hasta resolver el resultado; el reintento explícito reutiliza event_id
con MFA vigente. La prueba cancela solo después de que el dueño recibió el
cuerpo, observando una única llamada y ninguna repetición automática.

Pasaron vet/race de admin, doce tests de contratos y OpenAPI 3.1, integridad de
vendor desde v0.13.0 e imagen admin con red deshabilitada. Tests HTTP usan JWT
firmados y verificadores separados; el ensayo Keycloak real recorre la ruta de
producción admin→proxy→guard del dueño, comprobando identidad/cuerpo. Ese último
dueño es una fixture HTTP autenticada: no sustituye el ensayo PostgreSQL de user
ni declara todavía una prueba conjunta de consola y BD. Evidencias locales:
.local/p04-editorial-proxy-final-go.log, .local/p04-editorial-proxy-keycloak.log,
.local/p04-editorial-proxy-image.log y .local/p04-editorial-proxy-vendor.log.
Recursos de ensayo retirados; solo RustFS original permanece saludable.

Siguen pendientes consola web/login staff, provisión revisada de credenciales,
flujo editorial del cuestionario y activación atómica revisada del conjunto,
además del recorrido conjunto y rollout coordinado. Flags, cliente staff y DEV
persistente no se activaron ni migraron. Este incremento queda local, sin push.


### Incremento local V036: cuestionarios y conjunto editorial atómico

El catálogo tipado conserva los eventos y revisiones de documentos de V035 y
agrega cuestionarios al mismo flujo de autoría, revisión independiente y
publicación. User calcula el hash canónico del cuestionario y mantiene su clave
fuera del contrato público. Admin proporciona las rutas de proxy con las mismas
verificaciones independientes de sesión y audiencia.

La función activate_editorial_bundle confirma los cinco documentos, el vínculo
del cuestionario y la auditoría bajo una única transacción con versión esperada.
Se verificaron en PostgreSQL real: rechazo por tipo incluso con UUID/hash
coincidentes, vencimiento de MFA después de insertar auditoría con rollback
completo, reintento idéntico, un solo ganador concurrente, repetición histórica
sin retroceso y rechazo de adopción de un evento antiguo creado por SQL.
El ensayo de upgrade V035 conserva contenido, tiempos, eventos, revisiones y
cabecera de auditoría. Las 14 pruebas de contratos pasan, incluida la exclusión
de claves de respuesta públicas. Las pruebas Go de admin con race pasan.

No se ha aplicado V036 a DEV ni habilitado el cliente staff o sus flags. P04
permanece abierto: faltan consola web, provisión operativa, ensayo conectado y
publicación coordinada con manifiesto de revisiones y gates locales/remotos.

Verificación adicional: test_database_permissions.py terminó con código 0 en
.local/p04-assessment-bundle-permissions.log. Incluye bases fresh y upgrade V018,
migrador no superusuario, roles independientes, denegaciones y dump/restauración
sin contraseñas de roles. OpenAPI completo validado junto con sus 14 pruebas.
Commits locales relacionados: user c3b416d, admin fd78623, contratos de03bf2.

Verificación de los commits: vet y go test -race ./... de user finalizaron con
código 0 (.local/p04-assessment-bundle-go-complete.log), incluyendo la validación
pura de contenido sin atribuir aprobación. Los targets builder de user y admin
compilaron con --network none, usando vendor, con código 0; registros
.local/p04-assessment-bundle-user-image.log y
.local/p04-assessment-bundle-admin-image.log. Esto comprueba compilación de los
binarios; no equivale a una prueba de la imagen runtime ni a un despliegue.


### Base cliente de consola staff (local, todavía sin pantalla)

Frontend 4acea65 agrega EditorialApi con origen fijo, sesión staff inyectada,
rutas cerradas y comandos serializados una sola vez en memoria. Un resultado
incierto conserva evento/cuerpo para reintento explícito; no hay retry, refresh
MFA automático ni persistencia del contenido en preferencias. Respuestas se
limitan a 1 MiB, ocho segundos y sin redirecciones. Solo errores definidos de
rechazo se consideran definitivos; respuestas inesperadas de escritura siguen
siendo inciertas. Cinco pruebas cubren estos límites y el reintento estable.

Frontend b31187e prepara OidcAuthSession.staff con cliente rac-staff, manager
rac-staff-console y callback /staff/redirect.html, sin tocar Session.auth ni
provisionar /api/user/me. Solicita prompt=login y max_age=0 en el acceso
interactivo; la validación de AMR, antigüedad y permisos sigue en servidor.
Las doce pruebas de auth/editorial pasan en
.local/p04-staff-session-tests.log. Todavía no existe el callback/pantalla
conectado ni se declara probado este nuevo login en un navegador real.

El primer análisis global detectó package_config local desactualizado (intl y
flutter_localizations ausentes). flutter pub get --offline resolvió dependencias
sin cambiar el lockfile; la nueva ejecución de análisis continúa, sin declararla
aprobada antes de su resultado. Ningún flag de stack o cliente Keycloak activado.


### Entrada staff y callback compartido

Frontend 03c5c15 conecta /staff por navegación directa sin comprobar ni
aprovisionar Session.auth. La sesión verificada se consulta exclusivamente en
/api/admin/staff/session; presenta estados ausente/denegado/error/listo y acceso
interactivo/logout staff. Textos es/en en ARB. Las herramientas editoriales aún
indican En construcción, sin formularios que simulen aprobar o activar.

El callback /staff/redirect.html y el callback normal comparten oidc_callback.js;
una respuesta caducada vuelve a la entrada correspondiente. La transacción OIDC
continúa validada por el paquete y su manager, no se canjea código en JavaScript.
Falta ensayo de ambos callbacks en navegador tras esta extracción.

Cinco pruebas widget verifican estados y que la entrada directa no consulte la
sesión ordinaria. Detectaron navegación durante construcción y se corrigió con
post-frame. La suite completa pasó 89 pruebas en
.local/p04-staff-entry-full.log; el análisis posterior sigue en ejecución.
El análisis anterior, tras pub get offline, terminó sin incidencias en
.local/p04-staff-analysis.log. No se activaron flags ni se alteró DEV.


### Lectura editorial desde consola

Frontend 8f9c4f0 agrega consulta de documentos/cuestionarios privados por UUID,
solo cuando /staff/session incluye documents.read. Muestra contenido como texto
seleccionable, versión/idioma y SHA-256; no interpreta HTML. Cambiar referencia o
tipo elimina la revisión y una generación de solicitud impide que una respuesta
tardía restaure contenido anterior. No guarda contenido en preferencias ni logs.

Pasaron siete pruebas lector/entrada en .local/p04-editorial-reader-tests.log,
incluida carrera de cambio de referencia y representación literal de markup.
La autorización sigue en cada API; ocultar el widget no sustituye esos guards.
Pendientes formularios de borrador/revisión/publicación/activación, provisión,
recorrido real de ambos callbacks y conjunto completo, y rollout coordinado.
P04 permanece abierto; no hay push ni activación sobre DEV.


### Decisiones de consola: precondiciones y resultado incierto

Frontend d9918f8 prepara editorialDecision y EditorialDecisionAttempt, aún sin
botones conectados. Construye comandos desde la revisión cargada, con UUIDv4
seguro y hash exacto, sin actor/política cliente. Exige permiso propio, impide
revisión del autor y publicación sin aprobación; los guards de dueño siguen
siendo la autoridad. Un comprobante válido debe contener solo el identificador
esperado. No permite enviar de nuevo un intento ya resuelto o simultáneo.

Una respuesta 401 de reintento no resuelve una escritura 503 anterior: conserva
la incertidumbre y el mismo comando hasta comprobante válido. Tres pruebas
pasan en .local/p04-editorial-decision-tests.log. Queda conectar confirmación y
acciones, además de resolver conservación segura durante reautenticación con
navegación completa: el modelo actual es solo en memoria y no debe presentarse
como recuperación duradera. Borradores y activación también pendientes en UI.
