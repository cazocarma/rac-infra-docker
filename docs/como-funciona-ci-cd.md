# Cómo funciona CI/CD en RAC

## La receta y la máquina

GitHub Actions ejecuta recetas YAML versionadas en `.github/workflows/`. Un evento (`push`, `pull_request` o una ejecución manual) inicia un workflow. Este contiene jobs; cada job ejecuta pasos ordenados en un runner. En nuestra CI, GitHub proporciona una máquina Linux temporal por job. No es el PC de desarrollo y no hereda sus credenciales, archivos ignorados ni contenedores.

Un paso `uses:` llama una acción reutilizable, por ejemplo descargar código. Un paso `run:` ejecuta un comando. Fijamos las acciones a commits para controlar qué código de terceros se ejecuta.

## Integración continua: comprobar los cambios

Los workflows de los servicios prueban su código. Go usa `go test -race`; Flutter usa `flutter analyze` y `flutter test`. El workflow de infra, `ci.yml`, comprueba el conjunto:

1. `scope` (`scripts/ci_scope.py`) decide el alcance y ante cualquier duda
   ejecuta todo. Un PR que solo cambia Markdown fuera de `.github/` omite los
   jobs pesados. En un `push`, si el commit es exactamente el que ya pasó en
   su PR (un fast-forward), no se vuelve a probar el mismo árbol. `schedule`
   (lunes) y `workflow_dispatch` ejecutan todo e incluyen las mediciones de
   standing.
2. `workflow-policy` revisa sintaxis, acciones fijadas y rutas de los scripts,
   y siempre se ejecuta.
3. `migrations`: migraciones, permisos de base de datos, configuración
   DEV/QA/PRD y controles de despliegue.
4. `integration` corre en paralelo con `migrations`, en cuatro runners
   independientes. Cada suite levanta sus propias bases, brokers y proyectos
   Compose desechables:
   - `labs`: plataforma, vendor, políticas de match/chat, T&S, documentos y
     mensajería.
   - `services`: políticas de user, Keycloak/MFA, fotos S3 y EvidenceStore.
   - `standing`: carreras de JWT y commit con instancias Compose aisladas.
   - `stack`: `make up` levanta un DEV efímero; luego `make check
     test-integration` y Playwright con Chromium en desktop y móvil.

   Cada suite emite un token temporal con la GitHub App y descarga los
   repositorios a los SHA de `ci/companion-revisions.json`.
5. Al terminar se limpian contenedores y se revoca el token. Un fallo produce
   un check rojo y conserva los logs de Actions.

Un job omitido por alcance aparece como `skipped`, no como fallo. Para
comprobar a mano un cambio de documentación, ejecuta el workflow con
`workflow_dispatch`.

El Makefile evita mantener recetas operativas distintas para el PC y CI. Las credenciales de integración pertenecen a una App de lectura, no a la llave SSH personal del desarrollador. Véase [acceso de CI](ci-acceso-repositorios.md).

Verde significa que pasaron los casos programados para esa combinación de código. No demuestra ausencia de errores ni que otra combinación de commits de varios repositorios también funcione. Para exigir checks antes de mezclar un PR se necesitan reglas de rama; definir un workflow no activa esa protección por sí solo.

## Entrega y despliegue

CI prueba; CD prepara y lleva una versión a un ambiente. Con aprobación humana hablamos de entrega continua; desplegar automáticamente cada cambio válido sería despliegue continuo. En RAC el workflow `deploy.yml` es manual para QA/PRD.

Su entrada identifica un manifiesto de release con las imágenes Docker exactas por `sha256`. El script valida rama y confirmación, exige reviewers configurados en el environment y verifica la base de datos objetivo. PRD exige evidencia de un despliegue QA exitoso de esas mismas imágenes e infraestructura. Así se promueve una versión conocida, sin recompilar una variante al desplegar.

El código de ese mecanismo está preparado. Para operarlo faltan los hosts y runners de QA/PRD, sus archivos de secretos, imágenes/manifiestos reales y las protecciones de GitHub correspondientes. Una rama `prd` es una referencia de código; no crea un servidor productivo. El CI de infra no despliega en producción.

## Cómo leer una ejecución

Abrir Actions → ejecución → job → paso fallido. Leer el primer error relevante y distinguir preparación, permisos, build, migración, API o navegador. Los pasos omitidos después del fallo no son pruebas aprobadas. Corregir la causa y repetir las verificaciones afectadas; no ampliar permisos ni eliminar pruebas para obtener verde.

Referencias: [conceptos de GitHub Actions](https://docs.github.com/en/actions/get-started/understand-github-actions) y [protecciones de environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).
