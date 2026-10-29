# Provisión editorial DEV — pendiente de ensayo final

La provisión de base de datos está separada de `editorial_lab_fixture.py`.
`scripts/editorial_database.py` no crea usuarios de Keycloak, no asigna roles
humanos, no habilita listeners ni publica documentos o activa políticas.

Precondiciones: migraciones V034–V037 aplicadas mediante el migrador separado,
respaldo/recuperación de DEV revisados y conexión de operador controlada.
No ejecutar contra DEV por inferir autorización de una prueba desechable.
QA/PRD permanecen fuera de este adaptador: rechaza RAC_ENV distinto de dev.

Preparar fuera de Git `DOCUMENT_EDITORIAL_DATABASE_URL` con identidad fija
rac_documents_editorial y secreto independiente de al menos 24 caracteres.
El destino debe ser la base RAC seleccionada, host interno postgres, puerto
5432 y sslmode=disable exclusivamente en esta red DEV. No usar este transporte
en un ambiente productivo ni modificar la validación para aceptar URLs ajenas.
La variable se entrega por el entorno del proceso; no escribir su valor como
argumento, salida de consola o ejemplo versionado.

Invocación explícita desde infra: `make editorial-db-config ENV=dev`.
El target construye la imagen de herramientas y hereda la variable por nombre;
no se ejecuta como parte de up ni de la migración general. Después de crear la
identidad, abre una conexión con ella y verifica editorial_ready(). Los flags
DOCUMENT_EDITORIAL_ENABLED y STAFF_ACCESS_ENABLED continúan como estaban.

El operador exige transacción sobre la base exacta y privilegio de operador,
once funciones con firmas exactas, ausencia de membresías y de permisos sobre
tablas, columnas, creación en schemas o activación/auditoría crudas. Rechaza
autoridad inesperada en vez de intentar corregirla silenciosamente. Concede
CONNECT, USAGE y EXECUTE solo para el flujo editorial tipado. Repetir conserva
actor/cadena de auditoría; no crea otra cadena ni cambia decisiones históricas.

El proceso usa el secreto recibido para reconciliar la credencial. Una rotación
requiere coordinar la nueva credencial con el listener y probar reconexión; no
cambiarla unilateralmente mientras un servicio dependa de la anterior. Los
errores de CLI son genéricos y no imprimen DSN, secreto ni diagnóstico servidor.

Pruebas de validación: test_editorial_database.py. Ensayo real fresh/upgrade,
repetición y permisos negativos en test_database_permissions.py, resultado en
.local/p04-editorial-operator-permissions.log. Está en curso: este documento
no declara aprobado todavía ese ensayo ni configura la identidad humana/MFA.
