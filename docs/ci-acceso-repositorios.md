# Acceso entre repositorios en CI

La ejecución [39255195701](https://github.com/cazocarma/rac-infra-docker/actions/runs/39255195701) falló al descargar `rac-match-service`, antes de ejecutar migraciones. La anotación fue `repository ... not found`; GitHub también responde así cuando el token carece de acceso a un repositorio privado. El job integration se omitió porque dependía del job fallido. Los 34 segundos correspondieron a preparación y reintentos del checkout.

La llave SSH de este PC permite nuestros fetch/push locales. El runner de GitHub es otra máquina y no recibe esa llave. Su GITHUB_TOKEN está limitado al repositorio de la ejecución, por lo que no sustituye el acceso de lectura a otros repositorios privados. Véase [checkout de otros repositorios privados](https://github.com/actions/checkout#checkout-multiple-repos-private).

## Configuración requerida

1. Crear un [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new?name=RAC-CI-read&target_name=cazocarma&contents=read&expires_in=90), con vencimiento y acceso seleccionado a `rac-auth-service`, `rac-user-service`, `rac-match-service` y `rac-frontend-flutter`. Permiso de repositorio: **Contents: Read-only**; Metadata de lectura se incluye automáticamente. No necesita escritura, administración ni acceso a todos los repositorios.
2. Guardarlo como **repository secret** `REPO_READ_TOKEN` en [Settings → Secrets and variables → Actions de rac-infra-docker](https://github.com/cazocarma/rac-infra-docker/settings/secrets/actions). No guardarlo como variable, archivo de código o mensaje de chat.
3. Ejecutar nuevamente el workflow de la última versión de main. Si existe un token pero no funciona, revisar expiración, repositorios seleccionados, permiso Contents y existencia de la rama.

Referencias oficiales: [tokens de acceso personal](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) y [secrets de Actions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

## Comportamiento del workflow

El job migrations ejecuta las migraciones y verificaciones de infraestructura sin descargar repositorios externos. El job integration valida primero el token con GET de las referencias de las ramas, descarga los cuatro servicios y ejecuta las pruebas de políticas de base de datos, OIDC/API y navegador. La comprobación no imprime tokens ni cuerpos de error de GitHub y no cambia permisos o visibilidad de repositorios.

Faltar ese secret es un error explícito de configuración: no se omiten las pruebas de integración para presentar una ejecución verde. Los logs de contenedores y la limpieza solo se intentan si se llegó a crear la configuración DEV efímera.
