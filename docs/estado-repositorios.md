# Estado real de los repositorios

> Diagnóstico/preparación inicial. Ver [implementación vigente](implementacion-oidc.md) para los cambios posteriores.

Fecha: 2026-10-15. Inspección de `dev`; revisión estática, compilación y pruebas
acotadas. No es una auditoría completa de seguridad ni de todas las pantallas.

## Inventario

| Repositorio | Estado observado | Evidencia / límite |
| --- | --- | --- |
| rac-auth-service | API funcional básica en Go/Gin, fachada de Keycloak; login, refresh, logout y userinfo | `internal/http/router.go`; compila; login devuelve token. No tiene registro/social ni envelope que pide Flutter DEV |
| rac-user-service | Listado/detalle de compas, skills y escritura de perfil | `internal/http/router.go`, `internal/repo/postgres.go`; compila. Lecturas verificadas; perfil necesita esquema extendido y auth; skills mantiene TODO de autorización |
| rac-match-service | Reservas, disponibilidad, estados, extensión y listados; publicación AMQP | `internal/http/handlers.go`, `internal/service/match-service.go`; compila y health con DB responde. Consultas requieren schema que no está alineado |
| rac-chat-service | Servidor de health y estructura vacía | `cmd/server/main.go`; `go test ./...` falla por archivos Go vacíos. No hay chat ni WebSocket funcional |
| rac-payment-service | Servidor de health y estructura vacía | Mismo problema de archivos vacíos; no hay pagos implementados |
| rac-alert-service | Servidor de health y estructura vacía | Mismo problema; no hay consumidor de notificaciones implementado |
| rac-admin-service | Servidor de health y estructura vacía | Mismo problema; no hay API administrativa implementada |
| rac-frontend-flutter | Flutter Web con auth unificado, perfil, compas, reservas, settings y tema | Compila en Docker; interfaz más adelantada que backend auth. Único test es plantilla con import `package:app/main.dart` incompatible con nombre `rentacompa` |
| rac-infra-docker | Compose, NGINX y SQL compartido; ahora base y ajustes DEV/QA/PRD | Infra original esperaba servicios completos, realm ausente en DEV y checks con curl inexistente en Alpine. Cambios de esta revisión quedan locales |
| rac-shared-contracts | Intención documentada, sin contratos | Solo README; no hay OpenAPI, JSON Schema ni comprobación entre productor y consumidor |
| rac-docs | Archivo histórico | Documento técnico Word y README vacío; no se extrajo ni evaluó el contenido del Word en esta revisión |

Los cinco servicios inicialmente considerados planificados no tienen todos el
mismo estado: **match sí contiene lógica de negocio en DEV**. La primera
revisión de esta sesión usó MAIN y no incluyó ese trabajo. Chat, pagos, alertas
y administración continúan como esqueletos.

## Tecnologías

| Capa | Declaración encontrada | Alineación |
| --- | --- | --- |
| Go | auth: `go 1.24.0`; otros seis: `go 1.22`; Dockerfiles: `golang:1.24-alpine` | Misma familia, versiones declaradas diferentes. Compilación actual en Go 1.24 no prueba compatibilidad futura |
| HTTP Go | Gin 1.11 en auth, Gin 1.10 en el resto | REST coherente como enfoque; contratos y errores inconsistentes |
| Persistencia | `database/sql` + `lib/pq`, PostgreSQL 16/PostGIS 3.4 | Base compartida y esquema transversal; todavía no hay independencia de datos entre servicios |
| Identidad | Keycloak 24 + auth facade + JWT interno HS256 | Dos modelos de token sin contrato común; permisos y roles requieren cerrar integración |
| Mensajería | RabbitMQ 3-management; amqp091-go en match | Publicador existe; consumidores de negocio no están implementados; revisar tratamiento de errores de publicación |
| Frontend | Flutter 3.24.0 en Docker, Dart `>=3.4.0 <4.0.0`, HTTP y SharedPreferences | Compilación web disponible; mobile no probado. Tokens persistidos en SharedPreferences y guards basados en presencia de token |
| Proxy / runtime | NGINX 1.25-alpine, Alpine 3.19 | Imágenes antiguas y parcialmente fijadas: falta estrategia de actualización y digests |
| Almacenamiento | MinIO con tag de 2024 | Descarga observada con 401 en la preparación; no está activo ni integrado con los flujos comprobados |
| Entrega | Dockerfiles por aplicación, sin workflows CI encontrados | QA/PRD no pueden consumir versiones nuevas hasta publicar artefactos |
| Pruebas | Ningún `_test.go`; un widget test de plantilla | Ausencia de tests de negocio y de integración |

El stack es coherente como ejercicio Go + Flutter + Postgres + Keycloak. La
desalineación principal está en contratos, esquema y avance desigual, antes
que en la elección de lenguajes. No hace falta cambiar de stack para resolverla.

Go soporta una versión mayor hasta que existen dos mayores posteriores; la
historia oficial ya incluye Go 1.27, de modo que el builder 1.24 debe actualizarse
en un cambio dedicado. Fuente: [política e historial de Go](https://go.dev/doc/devel/release).
Seleccionar y probar una versión estable de Flutter desde su
[archivo oficial](https://docs.flutter.dev/install/archive), y planificar el salto
de Keycloak con su [guía de actualización](https://www.keycloak.org/docs/latest/upgrading/).
No se actualizaron frameworks ni imágenes de aplicación durante esta pasada.

## Diferencias que impiden funcionar de extremo a extremo

1. **Auth:** Flutter DEV exige `{ok,data,error}` en `shared/services/auth_api.dart`;
   Go devuelve `{keycloak,internal_jwt}` sin envelope en `internal/service/auth.go`.
   Login API entrega token, pero eso no hace funcionar el login de la interfaz.
   Flutter además llama `/register` y flujos sociales que no registra el router Go.
2. **Base de datos:** el SQL define `sesion` dos veces con `IF NOT EXISTS`.
   La segunda definición intenta agregar `creado_en` y `actualizado_en`, pero no
   altera la tabla ya creada. El repositorio match las usa en SELECT/INSERT/UPDATE.
   En el volumen previo tampoco se encuentran las columnas de perfil extendido:
   los scripts de init no se vuelven a ejecutar al arrancar.
3. **Identidades:** las semillas de PostgreSQL y los usuarios demo de Keycloak
   necesitan una correspondencia explícita de IDs. Revisar `sub`, `usuario.id`,
   `keycloak_id` y el `compa_id` usado por reservas antes de validar ese flujo.
4. **Autorización:** escritura de skills no exige identidad; match usa userinfo
   y depende de mappers de roles. Flutter omite Bearer al consultar availability,
   mientras match sí lo exige. Hay que acordar endpoints públicos y privados.
5. **Datos:** varios servicios consultan el mismo esquema. La división en repos
   todavía no constituye autonomía de microservicios; decidir propiedad de datos,
   contratos y límites antes de ampliar el número de servicios.
