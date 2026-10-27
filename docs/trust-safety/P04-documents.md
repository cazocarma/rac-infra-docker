# P04 — Documentos y aceptaciones (en desarrollo)

## Estado actual

Registro y linaje inmutables, consentimiento exacto y control transaccional
implementados en user, reservas/agendas y envíos nuevos de chat. Los servicios
usan platform v0.12.0; match/chat leen datos documentales por la autoridad HTTP
con credencial técnica y solo bloquean metadata de coordinación en PostgreSQL.
La garantía de confirmación depende de la base compartida actual, descrita en
[ADR-010](ADR-010-document-coordination.md).

No habilitado en el DEV persistente. P04 no está cerrado: quedan la lista
alineada al registro activo, intersticial/ARB, declaraciones y cuestionario,
historial, publicación humana aprobada, otros caminos de contenido público,
pruebas web conectadas y rollout coordinado. El historial siguiente conserva
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
