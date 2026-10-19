# Activación gratuita como compa

La pantalla Sé Compa permite a una cuenta cliente publicar su perfil sin postulación, aprobación administrativa ni pago. Solicita descripción, tarifa referencial CLP, entre una y ocho habilidades y al menos una franja semanal disponible. Una cuenta que ya tiene perfil puede editarlo; las habilidades reemplazan la selección anterior.

`GET /api/user/me/compa` consulta exclusivamente el perfil propio. `PUT /api/user/me/compa` valida el cuerpo completo, rechaza campos desconocidos y toma la identidad del JWT verificado. No admite usuario, rol ni estado de suscripción elegidos por el cliente. Descripción, habilidades y disponibilidad se guardan en una transacción en la base compartida actual. Usa las tablas existentes y la columna de zona horaria incorporada por V006.

Para la primera activación, backend-user asigna el rol fijo compa mediante la [API oficial de Keycloak 24](https://www.keycloak.org/docs-api/24.0.5/rest-api/index.html#_role_mapper). El rol incluye cliente, por lo que un compa conserva la capacidad de contratar a otros. Un JWT antiguo sigue teniendo sus permisos anteriores. Flutter renueva el token OIDC y verifica el rol devuelto por la API antes de habilitar el acceso a la agenda. Si falla la renovación, muestra que el perfil se guardó y permite actualizar la sesión sin perder los datos.

## Configuración y permisos

`make identity-config` configura el cliente confidencial `rac-compa-provisioner`, sin login interactivo ni password grant, con service account y `fullScopeAllowed=false`. Solo backend-user e identity-config reciben `COMPA_PROVISIONER_SECRET`, diferente por ambiente. Nunca se incluye en Flutter, tokens de cliente, repositorio o logs. Las credenciales master-admin se usan exclusivamente en la herramienta de configuración y pruebas DEV.

La cuenta de servicio tiene `manage-users` y `view-realm` del cliente realm-management, y su scope se limita a esos permisos. Estos permisos administrativos siguen siendo amplios dentro de rentacompa: el código solo expone la asignación fija de compa al sujeto autenticado. Antes de PRD, además de actualizar Keycloak, hay que restringir esa facultad mediante permisos administrativos granulares verificados para la versión elegida y proteger/rotar el secreto. No se presenta esta configuración DEV como aislamiento administrativo por rol.

Si falla la asignación remota, la transacción local se revierte y el perfil nuevo no aparece en búsqueda. Keycloak y PostgreSQL no comparten una transacción: si Keycloak asignó compa pero falla el commit local, el rol gratuito puede quedar concedido sin perfil. Reintentar es seguro: la asignación es idempotente y existe un único perfil por usuario. No se asignan admin ni suscripción. La API no cambia contraseñas, correo o identidades.

## Horarios y reservas

Cada compa elige una zona IANA (por defecto America/Santiago para perfiles nuevos). Los horarios se ingresan como horas locales de esa zona, con hasta tres franjas por día, sin cruces de medianoche ni superposiciones. Dejar un día vacío significa no disponible. V006 añade `compa_availability.zona_horaria` con UTC para conservar los horarios anteriores sin reinterpretarlos. Omitir zona_horaria en un cliente antiguo conserva el valor existente.

Match-service calcula los inicios disponibles en el servidor para el día local del comprador. Respeta cambios de hora, no ofrece horas inexistentes y distingue las dos ocurrencias de una hora repetida por su instante UTC. La UI presenta la hora local del dispositivo y su zona/offset. También excluye las solicitudes pendientes y reservas activas; la creación comprueba de nuevo disponibilidad y solapamientos. Las reservas ya creadas conservan sus instantes UTC, y los cupos semanales siguen usando America/Santiago por regla de negocio.


El plan gratuito permite tres confirmaciones por semana de la actividad en America/Santiago. Recibir solicitudes no consume cupos. Publicar o editar un perfil no activa una suscripción ni genera cobros.

## Pruebas

Go valida entradas, normalización de habilidades, asignación exclusiva de compa, errores de identidad sin secretos, rollback y reintento. `scripts/test_migrations.py` ejecuta las pruebas de transacción sobre PostgreSQL desechable. `make test-integration` incluye `test_onboarding.py`: crea una identidad marcada y temporal, comprueba cliente → compa con renovación real de tokens, edición, disponibilidad y recepción/aceptación de una reserva. Elimina exclusivamente esa identidad y sus registros al terminar. QA/PRD no ejecutan estas cuentas de demostración.

`test_browser_onboarding.py` verifica el formulario en escritorio y captura móvil 320×568, el guardado de los siete días, la renovación real de sesión, tres cupos en la agenda y edición persistente de habilidades. Crea y elimina su propia identidad con nombre y correo de prueba; no promociona las cuentas cliente1/cliente2. Las pruebas y workflows se incluyen en la entrega de código; los despliegues QA/PRD requieren aprobación y configuración de sus hosts.
