# P04 — Documentos y aceptaciones, primer incremento

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
