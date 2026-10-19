# Validación de la implementación

15 de octubre de 2026, DEV local. Esta revisión sucede al diagnóstico inicial.

| Comprobación | Resultado |
| --- | --- |
| Go 1.27.2, siete repositorios | `go vet` y `go test -race -count=1 ./...` pasan |
| Seguridad JWT | Firma incorrecta, issuer/audiencia incorrectos, vencidos, malformados e ID tokens rechazados |
| Permisos | Compa hereda base; base no publica ni edita skills; otro compa no edita un perfil ajeno; listados/reservas ajenos denegados |
| Flutter 3.44.0 | Análisis sin issues y seis tests de sesión/roles/interfaz/migración de tokens de preferencias |
| OIDC web real | Chromium: navegador Keycloak, callback PKCE, inicio en Flutter y logout |
| OIDC/API real | Code + S256 con tres roles y dos usuarios extra; verifier erróneo rechazado; identidad canónica, publicación, reserva, compa como comprador, aislamiento de recursos y revocación de refresh |
| Migraciones | Base vacía, adopción con datos, repetición y checksums alterados; todo validado en Docker aislado |
| DEV existente | V001–V003 aplicadas sin borrar los datos anteriores; dump previo conservado localmente |
| Entornos | DEV/QA/PRD validados con datos sintéticos; QA/PRD sin build, seeds ni puertos de datos publicados |
| Observabilidad | Tres targets Prometheus UP, dashboard Grafana provisionado y logs de APIs recibidos en Loki |
| Proxy | Configuración NGINX válida; recrear frontend no deja upstream fijado a una IP antigua |
| Android | APK debug compilado; callback nativo y plugin de almacenamiento incluidos |
| Contrato | OpenAPI 3.1 validado con openapi-spec-validator |
| Workflows | Todos los YAML de Actions validados con actionlint; gates inválidos rechazan antes de usar credenciales/red |

Las pruebas de migraciones usan contenedores/redes con nombres aleatorios y
datos en tmpfs; nunca toman secretos del `.env` ni borran volúmenes DEV.
La integración usa solo usuarios demo y elimina únicamente las reservas que
ella misma crea. No hay pruebas que carguen pagos.

Los logs de estas comprobaciones están en la carpeta padre local, fuera de
Git: `rac-go-race-tests.log`, `rac-frontend-final-tests.log`,
`rac-integration-tests.log`, `rac-browser-tests.log`, `rac-migration-tests.log`,
`rac-android-build.log`, `rac-contract-validation.log`,
`rac-workflow-validation.log` y `rac-proxy-recreate-test.log`.

No se ejecutó iOS localmente (este host es Windows), ni una sesión de login
en un teléfono físico. No se probaron runners, aprobaciones o despliegues
remotos: los workflows todavía son cambios locales. Tampoco se ensayó una
restauración del backup o una actualización de la base interna de Keycloak.
