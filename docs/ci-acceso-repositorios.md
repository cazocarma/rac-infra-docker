# Acceso entre repositorios en CI

## Causa y decisión

La ejecución [39255195701](https://github.com/cazocarma/rac-infra-docker/actions/runs/39255195701) falló al descargar `rac-match-service`, antes de ejecutar migraciones. La anotación fue `repository ... not found`: GitHub también responde así cuando el token no puede leer un repositorio privado. Los 34 segundos correspondieron a preparación y reintentos del checkout. Las advertencias de Node no fueron la causa.

La llave SSH del PC permite fetch/push locales. El runner es otra máquina: no recibe esa llave y su `GITHUB_TOKEN` está limitado al repositorio de la ejecución. Véase [checkout de otros repositorios privados](https://github.com/actions/checkout#checkout-multiple-repos-private).

Usamos una GitHub App dedicada de lectura. Su identidad pertenece a la automatización; no utiliza un token personal ni una llave SSH personal. La instalación selecciona repositorios y permite emitir tokens temporales por job. Un PAT depende de una persona y requiere mantener su vencimiento; una deploy key por repositorio multiplicaría las llaves que administrar. La App resuelve este acceso común con el mecanismo oficial de GitHub.

## Registro e instalación

1. En [Developer settings → GitHub Apps](https://github.com/settings/apps), registrar `RAC CI Read - cazocarma` (nombre único).
2. Homepage: `https://github.com/cazocarma/rac-infra-docker`. Desactivar Webhook. No se requieren callbacks, OAuth de usuarios, Device Flow ni eventos.
3. Repository permissions: **Contents: Read-only**. Metadata de lectura se agrega automáticamente. Los demás permisos quedan sin acceso, incluidos Actions, Secrets y Administration.
4. Visibilidad: **Only on this account** (`cazocarma`).
5. Instalar con **Only select repositories**, seleccionando exactamente `rac-auth-service`, `rac-user-service`, `rac-match-service`, `rac-chat-service` y `rac-frontend-flutter`.
6. En Credentials → Key pairs → New key de la App, generar una private key y guardar el PEM fuera del checkout, protegido. Nunca enviarlo al chat, imprimirlo en logs ni versionarlo.
7. En [Actions de rac-infra-docker](https://github.com/cazocarma/rac-infra-docker/settings/secrets/actions), configurar:

| Tipo | Nombre | Valor |
| --- | --- | --- |
| Repository variable | `RAC_CI_APP_CLIENT_ID` | Client ID de la App, no un client secret ni el App ID |
| Repository secret | `RAC_CI_APP_PRIVATE_KEY` | Contenido completo del PEM de la App |

La App no necesita instalarse en infra: el workflow usa su `GITHUB_TOKEN` para infra y solicita explícitamente el token de instalación para los cinco compañeros. No otorgar acceso a todos los repositorios como solución a un error.

## Comportamiento del workflow

El job `migrations` verifica la infraestructura sin descargar repositorios externos. `integration` valida la configuración y usa `actions/create-github-app-token` v3, fijada a un commit registrado en `docs/action-pins.json`. Solicita los seis repositorios y `permission-contents: read`. La acción revoca el token al terminar el job; GitHub limita su duración a una hora y el job tiene timeout de 55 minutos.

El preflight comprueba lectura de las referencias antes de descargar código. Los checkouts no persisten credenciales. Las pruebas incluyen políticas de base de datos con los servicios compañeros, OIDC/API y navegador. La falta de configuración falla explícitamente: no se omiten pruebas para obtener un resultado verde. Ya no se consume `REPO_READ_TOKEN`.

En push y pull request se leen los cinco SHA completos de `ci/companion-revisions.json`. El preflight valida el conjunto exacto y comprueba acceso a cada commit. Los cambios de versión se revisan por PR; no hay fallback a una rama móvil. No se usa `pull_request_target`: los PR de forks no reciben secretos y requieren integración desde una rama interna revisada. Revisar especialmente cambios de workflows y scripts ejecutados por CI antes de ejecutarlos con secretos. La App no incluye despliegue, producción, pagos ni escritura.

## Verificación y diagnóstico

Después de configurar App y Actions, ejecutar el workflow de la versión actual de main. Verificar emisión del token, comprobación de acceso, cinco checkouts y pruebas reales. Los tests unitarios del preflight no sustituyen esta verificación.

- Configuración ausente: comprobar nombres y que sean variable/secret **del repositorio infra**, no de un environment que el job no utiliza.
- Fallo al emitir token: revisar Client ID, PEM completo e instalación en `cazocarma` con los seis repositorios.
- HTTP 403/404: revisar instalación, Contents de lectura y existencia del commit fijado. Un 404 no demuestra que el repositorio no exista.
- Error de red: reintentar y revisar el estado de GitHub. No ampliar permisos.
- Si la emisión funciona pero una prueba falla, investigar esa prueba por separado.

No registrar tokens, PEM ni cuerpos de respuestas de autenticación. El preflight solo informa repositorio, revisión y código HTTP.

### Navegador Linux: idioma explícito

Tras corregir el acceso, el intento 2 llegó a las pruebas web pero no encontró el botón inicial. La reproducción con Chromium de Playwright 1.55.0 en Linux mostró `navigator.language = en-US@posix` y un error de Flutter: `Incorrect locale information provided`. Con `locale='es-CL'`, el mismo navegador mostró el login correctamente. Las pruebas de reservas y onboarding fijan ahora idioma `es-CL` y zona `America/Santiago`, sin depender del locale del sistema del runner. Un fallo de arranque informa también los errores JavaScript recolectados. Esto es independiente de las credenciales de la App; no se amplían permisos ni se oculta el fallo con reintentos.

### Pantallas implementadas y pruebas de aceptación

La ejecución `39447271885`, intento 2, pudo emitir el token y descargar los cinco repositorios después de incluir `rac-chat-service` en la instalación. El siguiente fallo fue una expectativa antigua de `test_browser.py`: exigía «En construcción» al abrir Mensajes, aunque el frontend fijado ya implementaba el chat. La prueba ahora exige una respuesta HTTP 200 del listado privado, su colección `items` y los controles reales de Mensajes. El recorrido bidireccional, la recuperación de red y el acceso de solo lectura se verifican en `test_chat_browser.py`. Actions muestra cada recorrido web en un paso separado; no se omiten pruebas ni se amplían permisos para resolver errores de aceptación.

La regresión completa local también detectó una carrera en la automatización del editor Flutter: el campo semántico cambia su nombre al recibir foco, y la respuesta HTTP de envío puede llegar antes de que se restablezca el compositor. El test enfoca la pestaña, espera el editor listo y verifica el contador y el botón habilitado después de enviar. No agrega pausas fijas ni reintentos de envío para ocultar el fallo. Ante un envío fallido guarda captura y árbol accesible localmente, sin registrar credenciales.

La siguiente ejecución, `39456030382`, aprobó login/reservas y onboarding, pero detectó una carrera al buscar la reseña pública. El test debe esperar la carga del perfil y la respuesta de reseñas antes de recorrerlo; desplazar durante la transición puede saltarse el contenido. Se verifica también que el POST incluya el comentario y que la API pública lo devuelva, para distinguir escritura, lectura y presentación. El identificador del perfil de compa y el de su usuario son distintos; la observación de la respuesta usa la ruta pública real.

Al ampliar el chat, `39520731959` encontró dos nodos con el mismo contador de caracteres: el contador visible y `flt-announcement-polite`, el anuncio del lector de pantalla. Las comprobaciones ahora se limitan al diálogo de reseña o al árbol `flt-semantics-host`, excluyendo anuncios globales sin deshabilitar accesibilidad. Verifican además el valor del editor y el cuerpo realmente enviado. Los recorridos web independientes continúan aunque falle otro, siempre que el runtime se haya instalado; el job mantiene el resultado de fallo. Solo al fallar se conservan durante tres días capturas y árboles accesibles de chat/reseñas de los fixtures sintéticos de CI, mediante rutas explícitas que excluyen `.env`, tokens y claves.

## Operación y rotación

La clave privada es persistente y **no expira automáticamente**. Rotarla periódicamente (política inicial RAC: cada 90 días) y al sospechar exposición: generar una segunda clave, actualizar el secret, validar una ejecución y eliminar la anterior en GitHub. GitHub admite varias claves durante la transición. Ante exposición confirmada, revocar inmediatamente la clave afectada y los tokens activos.

Conservar el PEM en un gestor de secretos o almacenamiento protegido. Limitar quién modifica workflows y secretos de infra. Eliminar copias temporales después de verificar el secret. Si se configuró un PAT para esta finalidad, revocarlo después de validar la App. Este cambio no automatiza la rotación.

Para retirar acceso, suspender o desinstalar la App y eliminar secret y variable. Al agregar repositorios, revisar expresamente instalación y lista del workflow.

## Referencias oficiales

- [GitHub App en Actions](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/making-authenticated-api-requests-with-a-github-app-in-a-github-actions-workflow)
- [Acción oficial y entradas](https://github.com/actions/create-github-app-token)
- [Tokens de instalación y duración](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)
- [Administración y rotación de claves privadas](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps)
- [Secrets de Actions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)

Al incorporar alertas, la lista vigente agrega `rac-alert-service`, manteniendo Contents read-only. Las menciones a cinco repositorios en diagnósticos históricos describen esas ejecuciones anteriores.
