# DEV, QA y PRD

> Diagnóstico/preparación inicial. Ver [implementación vigente](implementacion-oidc.md) para los cambios posteriores.

## Ramas

Los 11 repositorios tienen `dev`, `qa` y `prd` locales, con seguimiento de sus
respectivas ramas en `origin`. `dev` ya existía; se preservó su historial.
`qa` y `prd` se crearon desde el `origin/main` de cada repositorio.
No se fusionaron ramas ni se modificó la rama predeterminada `main` de GitHub.
No se publicaron commits nuevos: solo las referencias nuevas `qa` y `prd`.
Los clones de este PC están en `dev`.

Flujo propuesto: ramas de trabajo desde `dev`, integración y pruebas en `dev`,
promoción revisada a `qa` y luego a `prd`. Los commits de merge de `main` y los
cambios exclusivos de `dev` deben reconciliarse explícitamente antes de la
primera promoción; no asumir que las ramas están sincronizadas.

Promover la misma imagen por digest entre QA y PRD evita reconstruir un artefacto
distinto. Flutter incorpora las URLs al compilar: antes de conseguir esa promoción
sin reconstrucción hay que usar URLs relativas/configuración en ejecución o un
dominio común adecuado. Hoy QA y PRD deben recibir la imagen de frontend que
corresponda a sus URLs; esa limitación sigue pendiente.

Las protecciones de ramas, revisiones obligatorias, CI y GitHub Environments
todavía no están configurados. Las ramas por sí solas no los activan.

## Archivos

| Archivo | Responsabilidad |
| --- | --- |
| `Makefile` | Comandos del proyecto; DEV por defecto |
| `compose.yaml` | Servicios y configuración compartida |
| `docker-compose.dev.yaml` | Construcción desde repositorios hermanos, herramientas y datos demo |
| `compose.release.yaml` | Imágenes publicadas y reinicio de servicios para QA/PRD |
| `docker-compose.qa.yaml` | Ajustes propios de QA |
| `docker-compose.prd.yaml` | Ajustes propios de PRD |
| `envs/.env.<entorno>.example` | Plantillas versionables |
| `envs/.env.<entorno>` | Valores reales ignorados por Git |
| `envs/realm.dev.example.json` | Realm de desarrollo con usuarios ficticios |
| `envs/realm.dev.json` | Copia local ignorada por Git |

Compose combina la base y los ajustes mediante `-f`; el Makefile selecciona
los archivos y pasa `--env-file` explícitamente para resolver variables.
[Referencia de Docker](https://docs.docker.com/compose/how-tos/multiple-compose-files/).

## DEV en este PC

Desde `rac-infra-docker`:

```sh
make up
make ps
make check
make logs SERVICE=backend-match
make stop
```

El Makefile de la carpeta padre delega en este repositorio por compatibilidad.
La configuración anterior de `.local` queda como respaldo; no usarla junto
con la nueva porque publica los mismos puertos y referencia los mismos datos.
Los contenedores `rac-local` anteriores se dejaron detenidos.

Para una instalación nueva, copiar `envs/.env.dev.example` a `envs/.env.dev` y
`envs/realm.dev.example.json` a `envs/realm.dev.json`. Los repositorios de auth,
usuarios, match y Flutter deben estar al lado del repositorio de infraestructura.

| Servicio | Acceso DEV | Credencial demo |
| --- | --- | --- |
| Flutter y API | http://localhost | cliente1 / 123456 en Keycloak; OIDC/PKCE en la misma pestaña |
| Keycloak | http://localhost:8081 | admin / admin |
| pgAdmin | http://localhost:5050 | admin@example.com / admin123 |
| RabbitMQ | http://localhost:15672 | guest / guest |
| PostgreSQL | localhost:5432 | postgres / postgres; DB rentacompa |

Dentro de Docker, PostgreSQL se llama `postgres`; las APIs usan `backend-auth`,
`backend-user` y `backend-match`. Se desactivó `AUTH_MOCK`.

Este PC reutiliza `rac-local_pgdata`, `rac-local_rabbitmq-data` y
`rac-local_pgadmin-data` mediante variables locales `DEV_*_VOLUME`, sin copiar
ni eliminar datos. Una instalación nueva usa volúmenes `rac-dev_*`.
QA y PRD tienen proyectos separados `rac-qa` y `rac-prd` y volúmenes propios;
no configurar esas variables DEV en otros entornos.

El volumen existente conserva el esquema previo: no se aplicaron cambios de
negocio ni migraciones automáticas. Los scripts de inicialización solo corren
cuando PostgreSQL encuentra un volumen vacío. Reiniciar no migra una base.

`make stop` conserva los contenedores y datos. `make down` elimina contenedores
y red, conservando volúmenes. No hay objetivo que elimine los datos.

## QA y PRD en otro host

1. Preparar el host, Docker/Compose, disco persistente, DNS y proxy con TLS.
2. Llevar una versión revisada de infraestructura y completar una copia de
   `envs/.env.qa.example` o `envs/.env.prd.example`, con credenciales diferentes
   por entorno. Codificar caracteres especiales en las URLs de conexión.
3. Construir/publicar las imágenes mediante un proceso de entrega todavía
   pendiente y configurar `AUTH_IMAGE`, `USER_IMAGE`, `MATCH_IMAGE`, `CHAT_IMAGE` y
   `FRONTEND_IMAGE` con digest o tag de commit; no usar `latest`.
4. Configurar el realm `rentacompa`, el cliente `frontend`, los roles y sus
   mappers en Keycloak. QA/PRD no importan usuarios demo ni el realm DEV.
5. Resolver los bloqueos de aplicación y migraciones listados en `pendientes.md`,
   respaldar la base y ensayar restauración y rollback antes del despliegue.
6. Validar con `make ENV=qa config` o `make ENV=prd config`. Después de completar
   los pasos anteriores, `make ENV=qa up` o `make ENV=prd up` consume las imágenes
   publicadas sin construir código del checkout local.

Los secretos obligatorios vacíos hacen fallar Compose. Los archivos
`.env.qa.validation` y `.env.prd.validation` de este PC contienen valores
ficticios para validar estructura; están ignorados y no sirven para desplegar.
No se crearon archivos con credenciales reales de QA/PRD.

QA publica por defecto el proxy en `127.0.0.1:8080` y Keycloak en `127.0.0.1:8082`;
PRD usa `127.0.0.1:8088` y `127.0.0.1:8083`. El proxy TLS del host debe reenviar
tráfico a esos puertos. Bases de datos y RabbitMQ no publican puertos en QA/PRD.
Para checks con otro puerto/dominio: `make ENV=qa CHECK_URL=https://qa.example.com check`.
Keycloak usa modo `start` en QA/PRD, pero el TLS y las cabeceras confiables
dependen del proxy de ese host: no está configurado en este PC.

El esquema legado se ejecuta solo al inicializar una base vacía, sin seeds
de aplicación en QA/PRD. El bootstrap de Keycloak crea rol/base/esquema sin
eliminar datos. Eso no reemplaza un sistema de migraciones ni asegura que
las consultas de todos los servicios funcionen.

MinIO, chat, pagos, alertas y administración están fuera de la configuración
activa hasta resolver sus bloqueos. No hay un entorno productivo desplegado.

## Activación compa

Cada ambiente necesita `COMPA_PROVISIONER_SECRET` en su archivo local. Lo consumen exclusivamente identity-config y backend-user. Ejecutar `make ENV=<ambiente> identity-config` configura la cuenta de servicio dedicada y los clientes rac-web/rac-mobile; no usar el cliente frontend heredado. Véase [activación y permisos](activacion-compa.md). Las migraciones versionadas actuales se aplican con `make ENV=<ambiente> migrate`, con historial en meta.schema_history; los párrafos de estado inicial anteriores describen el diagnóstico previo, no la implementación actual.
