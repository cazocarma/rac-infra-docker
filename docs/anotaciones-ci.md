# Ronda de anotaciones de Actions — 21 de octubre de 2026

## Causas comprobadas

En los últimos CI de infraestructura y frontend aparecen dos grupos comunes: acciones cuyo action.yml aún declara Node 20, aunque GitHub las fuerza a Node 24; y el aviso de migración de ubuntu-latest a Ubuntu 26. Android muestra además la deprecación de setup-java v4. El aviso de capacidad de los runners macOS arm64 pertenece a GitHub y no se corrige cambiando código ni ocultando anotaciones.

Se revisaron los workflows de diez repositorios; rac-docs no tiene workflow. Los siete servicios Go comparten las mismas referencias antiguas y reciben la misma actualización. Se mantienen ramas/PR existentes cuando corresponden y se abren ramas de mantenimiento para auth, match, admin y payment.

## Cambio aplicado

Se actualizan checkout, setup-go, upload-artifact, setup-java y las tres acciones Docker a releases estables que declaran node24, conservando SHA completo. Las versiones y runtimes auditados están en action-runtimes.json; action-pins.json sigue siendo el registro de referencias. Flutter-action ya usa composite y su caché interna usa actions/cache v5; create-github-app-token v3 ya declara node24. No se agregan flags para forzar el runtime ni se reducen permisos, pruebas o aprobaciones.

Los jobs Linux alojados se fijan en ubuntu-24.04. macos-15 ya estaba fijado y no cambia. Los runners propios QA/PRD conservan sus etiquetas; antes de provisionarlos deben usar Actions Runner >=2.327.1 para Node 24 (>=2.329.0 si se necesitan comandos Git autenticados desde acciones Docker). No hay hosts productivos ni se ejecuta deploy durante esta ronda.

Se revisaron los cambios de las releases: checkout conserva persist-credentials:false y las protecciones para eventos no confiables; no se usa pull_request_target. setup-java sigue instalando Temurin 17. upload-artifact mantiene el archivo comprimido por defecto: no se activa archive:false, por lo que se conservan los nombres/colecciones actuales. Las acciones Docker mantienen los inputs de contexto, tags, provenance y SBOM. No se actualizan versiones de Go/Flutter/Java ni dependencias de la aplicación.

## Prevención y verificación

scripts/check_actions.py comprueba que cada referencia local esté fijada y revisada, que su auditoría corresponda al SHA y declare un runtime admitido, y que Linux no vuelva a ubuntu-latest. Rechaza flags para ocultar el runtime antiguo. Se ejecuta en CI; --workspace .. permite inspeccionar los repositorios hermanos localmente. Sus pruebas incluyen regresión a Node 20, etiqueta mutable, imagen flotante y falta de auditoría. El registro es una revisión del metadata en un commit inmutable; actualizar acciones requiere volver a inspeccionarlo, no editar solo el nombre del runtime.

La validación remota debe comprobar resultado y anotaciones del commit nuevo. Las anotaciones de ejecuciones históricas permanecen en GitHub y no se eliminan. Los avisos externos de capacidad del runner se informan aparte, sin alterar la matriz para esconderlos.

Fuentes oficiales: [retiro de Node 20](https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-in-github-actions/), [migración de Ubuntu](https://github.com/actions/runner-images/issues/14748), [releases de checkout](https://github.com/actions/checkout/releases), [upload-artifact v7](https://github.com/actions/upload-artifact/releases/tag/v7.0.0). Las releases específicas de cada acción se enlazan mediante su tag en el registro de runtimes.
