# Implementación OIDC, migraciones, permisos y observabilidad

Estado del trabajo local en DEV, 15 de octubre de 2026. Este documento sucede
al diagnóstico inicial `estado-repositorios.md`; los hallazgos históricos se
conservan para mostrar qué se corrigió. No se publicaron estos cambios.

## Identidad para web y móvil

Se adoptó Authorization Code + PKCE S256 con Keycloak. Flutter usa `oidc`
5.0.2, con verificación de firma de ID token, issuer, nonce/state y refresh
gestionados por la biblioteca. Web usa el cliente público `rac-web`; Android
e iOS usan `rac-mobile`. Ninguno tiene un client secret. Se deshabilitaron
implicit, password grant y el cliente legado `frontend`.

El login y registro se muestran en el navegador del proveedor; la aplicación
ya no recibe contraseñas. Proveedores sociales se configuran en Keycloak cuando
existan sus credenciales, sin endpoints sociales propios ni mocks.
`rac-auth-service` conserva userinfo verificado y telemetría, sin emitir JWT
internos ni reenviar contraseñas. Recursos Go verifican firma RS256, issuer,
audiencia `rac-api`, vencimiento, tipo Bearer y roles; no aceptan ID tokens.
Se descarga JWKS por la URL interna de Docker, manteniendo la validación del
issuer público: no se desactivó la verificación de issuer.

En web el login y logout navegan en la misma pestaña, con `originalUri` a la
raíz de RAC. El callback conserva la respuesta y vuelve a la app; `manager.init()`
valida state, nonce, PKCE, firma e issuer antes de habilitar la sesión. El arranque
completa `/api/user/me` antes de mostrar el inicio. Recargar conserva la sesión.
`OidcWebStore` 1.2.2 cifra access/refresh/ID tokens y el verificador PKCE con
AES-GCM y clave no exportable en IndexedDB. `encryption: required` impide
persistencia en texto plano si el navegador no admite el cifrado. Esto no
protege frente a XSS ejecutado en el mismo origen. Móvil conserva el almacenamiento
seguro nativo. No se guardan tokens en SharedPreferences.
Referencia: [uso y retorno en la misma página](https://bdaya-dev.github.io/oidc/oidc-usage/).

Logout revoca refresh y cierra la sesión del proveedor; un access token JWT
ya emitido puede seguir válido hasta su vencimiento (5 minutos en los clientes
configurados). Revocación instantánea requeriría introspección u otro mecanismo.

La identidad del dominio se resuelve en `/api/user/me`: `usuario.id` conserva
su identidad histórica y `keycloak_id` guarda el `sub` del token verificado.
El cliente no puede elegir el usuario que modifica ni otorgarse roles.
Los endpoints de reservas normalizan el ID de perfil de compa a `usuario_id`.
La pantalla de reserva usa la API real; la agenda consulta reservas propias,
contrataciones y solicitudes recibidas. No se simulan pagos ni planes.

### Configuración

Web carga `/config.json` al arrancar; NGINX lo genera con variables públicas
de entorno. Así la misma imagen web puede promoverse de QA a PRD sin recompilar
URLs. Native usa `--dart-define=API_BASE_URL=...` y `OIDC_ISSUER=...` al compilar;
el callback es `cl.rentacompa.app://oauth2redirect`.

Para un teléfono/emulador, `localhost` no identifica este PC. Hace falta un
issuer accesible con el mismo nombre desde dispositivo, navegador y APIs;
configurar HTTPS y el issuer en Keycloak/Compose/app de forma consistente.
No cambiar solo la URL del cliente ni omitir validaciones para salvar ese problema.
Los identificadores Android siguen siendo los de la plantilla; app ID definitivo,
firmas y entrega a tiendas se definen antes de distribución.

`make identity-config` aplica clientes/roles de forma idempotente y conserva
usuarios existentes. Solo DEV permite crear los usuarios de prueba y sus datos.
No elimina realms ni reconfigura proveedores externos.
Fuentes: [biblioteca Flutter OIDC](https://pub.dev/packages/oidc),
[configuración por plataforma](https://bdaya-dev.github.io/oidc/oidc-getting-started/),
[documentación Keycloak](https://www.keycloak.org/securing-apps/oidc-layers).

## Migraciones

La orquestación y SQL viven en `db/migrations` de infra. Flyway 11.15 registra
versiones y checksums en `meta.schema_history`, usa bloqueo de migración y
transacciones de PostgreSQL. `clean` está deshabilitado.

| Versión | Cambio |
| --- | --- |
| V001 | Adopta el esquema existente sin borrar datos; crea esquema inicial y campos de perfil |
| V002 | Timestamps de sesión, validación de rangos y exclusión de reservas simultáneas solapadas |
| V003 | Índices de identidad y listados |

```sh
make migrate
make migration-info
make migration-validate
```

DEV conserva `rentacompa` y los volúmenes anteriores. Las plantillas QA/PRD
seleccionan `rac_qa` y `rac_prd`; el overlay y su archivo de variables definen
el destino JDBC, credenciales migradoras y conexión de aplicaciones. No hay
SQL distinto por ambiente: se promueven las mismas migraciones. Las cuentas
demo son provisioning DEV separado del historial de esquema.

Antes de migrar este PC se guardó un dump local en `.local/backups` de la carpeta
padre. No se ejecutó `baselineOnMigrate`, `repair` ni una limpieza de datos.
V001 es idempotente para adoptar la base previa; desde ahora no se editan
migraciones aplicadas: se agrega V004, V005, etc. Si existen reservas históricas
solapadas, V002 falla y revierte; se deben reconciliar explícitamente, nunca
descartarlas automáticamente. Rollback operativo se planifica con backup y
restauración o una migración correctiva; no hay un `down` destructivo automático.

En PRD usar cuentas diferentes para migraciones y aplicación, con permisos
mínimos; las variables lo permiten, pero crear/grant de esas cuentas en el host
es un paso de provisioning que no se ha ejecutado. Keycloak mantiene su propia
base y su mecanismo de actualización; Flyway aquí administra el esquema RAC.

## Permisos

`cliente` es el nombre técnico del usuario base. `compa` incluye `cliente`;
`admin` incluye ambos. La autorización depende del token firmado y de quién
es dueño o participante del recurso, no de una selección en la interfaz.

| Acción | Política |
| --- | --- |
| Buscar/ver compas y catálogo de skills | Público |
| Perfil propio | Usuario autenticado; sub/email del token |
| Contratar y ver disponibilidad | Base, compa o admin |
| Publicar perfil de compa | Compa o admin; perfil propio |
| Cambiar skills/disponibilidad | Compa dueño o admin |
| Leer reserva | Cliente de esa reserva, compa de esa reserva o admin |
| Listar reservas de un usuario | El propio usuario o admin |
| Aceptar solicitud | Compa de la reserva o admin |
| Cancelar/finalizar | Participante autorizado y transición válida |
| Extender | Cliente de esa reserva o admin |
| Pagos, planes y desembolsos | Pendientes de diseño; no hay cargos implementados |

Otorgar el rol de compa se administra en Keycloak por ahora. El flujo de
solicitud/revisión de publicación y dashboards administrativos de producto
todavía no está implementado; no se permite autoelevar rol desde el perfil.
La política de verificación de correo, moderación/KYC y condiciones comerciales
se cerrará con ese flujo y los pagos. Roles desconocidos fallan con 403.
Contrato inicial: `rac-shared-contracts/openapi.yaml`.

## Observabilidad

```sh
make observe
```

Grafana: http://localhost:3000 (`admin` / `admin-local` solo DEV).
Dashboard provisionado: **RAC · Servicios**. Prometheus: http://localhost:9090.
Loki no publica puerto hacia Windows. Alloy recolecta logs del proyecto del
entorno mediante un proxy de Docker que admite lecturas y deshabilita POST;
su red de socket es interna. No se expone el socket Docker al navegador.

Los siete servidores tienen `/health` (vida), `/ready` (dependencias conocidas)
y `/metrics`. Auth/user/match son los servicios activos; los otros cuatro
continúan como servidores mínimos, ahora compilables y con telemetría.
Los checks de imagen y Compose usan readiness. Prometheus recoge requests,
errores, latencia y métricas Go de los tres servicios activos. Los logs de
requests son JSON y usan rutas de plantilla, sin bodies, tokens ni query strings.
No se usan identificadores de usuario como labels de métricas.

Hay reglas de indisponibilidad y tasa de errores. No se configuró un canal de
notificaciones/Alertmanager. Grafana es una herramienta operativa con cuenta
propia, no el dashboard de producto ni una concesión automática al rol admin
de la aplicación. En QA/PRD requiere credenciales propias y acceso restringido.
No hace falta un repositorio separado mientras este stack sea parte de RAC.
[Referencia de Alloy/Loki](https://grafana.com/docs/alloy/latest/tutorials/send-logs-to-loki/).

## Tests y CI/CD

```sh
make test-go
make test-flutter
make test-integration
```

Go usa `go vet`, `go test -race` y tests de JWT, permisos, estados, readiness y
métricas. Flutter usa `flutter analyze` y `flutter test`, más Playwright para
probar el flujo web real con Keycloak. La integración API prueba code/PKCE real,
verifier erróneo, permisos, IDs, reservas y revocación de refresh; no usa ROPC.
`scripts/test_migrations.py` crea Docker aislado para probar migraciones nuevas,
adopción con datos, repetibilidad y rechazo de checksum alterado.

Los workflows locales están en `.github/workflows` de cada servicio, Flutter
e infra; las acciones están fijadas por SHA. Los servicios publican imágenes
por SHA solo después de tests y compilación. Flutter agrega compilaciones
Android debug e iOS simulador como gates antes de publicar la imagen web.
Infra prueba migraciones, aislamiento e integración con los repos hermanos.

El despliegue se inicia manualmente desde la rama QA/PRD, exige texto de
confirmación, GitHub Environment con revisores y manifiesto con cuatro digests.
PRD exige un despliegue QA exitoso con ese mismo manifiesto. No reconstruye las
imágenes ni sustituye silenciosamente el release. Fallos quedan registrados
como despliegues fallidos, sin rollback de esquema destructivo.
La promoción también compara un hash del contenido de infraestructura,
observabilidad y migraciones: las cuatro imágenes por sí solas no bastan para
aprobar cambios de SQL que no se hayan probado en QA.

### Activación pendiente en GitHub y hosts

1. Revisar y publicar coordinadamente los cambios de repositorios y workflows.
2. Configurar checks obligatorios y PRs protegidos para QA/PRD.
3. Crear GitHub Environments `qa` y `prd`, con revisores y restricciones de rama;
   la disponibilidad de revisores depende del plan/visibilidad del repositorio.
   El script falla cerrado si no existe esta protección; no la crea desde YAML.
4. Configurar `REPO_READ_TOKEN` de solo lectura para checkouts cruzados privados.
5. Preparar runners Linux con labels `rac-qa` y `rac-prd`, Docker, Make y Python.
6. Configurar en cada Environment `RAC_ENV_FILE` con la ruta absoluta a secretos
   del host, HTTPS/Keycloak, permisos DB, backups y prueba de restauración.
7. Provisionar identidad y validar el host antes de la primera entrega.
8. Crear/revisar el manifiesto en `releases/`; completar los mismos digests en
   el host y ensayar QA antes de pedir aprobación para PRD.

No se activaron workflows, runners, protección de ramas ni despliegues remotos.
La CI de infra toma los últimos `dev` publicados de los servicios: por eso la
publicación inicial debe coordinarse. Para entregas, el manifiesto de imágenes
es el conjunto inmutable; no asumir igualdad de versiones entre repos.
[GitHub Environments y gates](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).

### Límites que siguen abiertos

Keycloak 24 y algunas imágenes de infraestructura heredadas necesitan una
actualización dedicada y ensayo de su propia migración antes de PRD; aquí se
actualizaron los toolchains de aplicación, no la base interna de Keycloak.
No se implementaron pagos/planes, chat, alertas de negocio ni dashboards de
producto. Falta diseñar esos flujos contigo. MinIO continúa desactivado.
La aplicación móvil todavía requiere prueba de login en dispositivo/emulador
con un issuer accesible; la compilación no sustituye esa prueba. El pipeline
iOS necesita ejecutarse en macOS. Nada de esto certifica PRD para uso real.
