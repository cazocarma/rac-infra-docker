# ADR-008 — Dependencias Go privadas sin credenciales de build

Estado: adoptada para user y match, 2026-10-23.

## Problema

`rac-platform` es privado. `GITHUB_TOKEN` de un servicio no puede descargar otro
repositorio privado. Solo infra recibe la llave de la App de lectura; distribuirla
a cada repositorio aumentaría los lugares desde los que se puede usar esa llave.
Un `replace` permanente contra un directorio hermano tampoco permite reproducir
el build de un checkout independiente.

## Decisión

Los consumidores fijan una versión publicada en `go.mod` y conservan el árbol
generado con `go mod vendor`, incluyendo licencias y `vendor/modules.txt`.
Es vendoring administrado por Go, sin forks ni cambios manuales de las reglas.
La fuente se modifica en platform y se publica antes de actualizar consumidores.
CI y Docker compilan con vendor, sin acceso al proxy ni a sumdb. Las imágenes
finales solo reciben binarios; ningún secreto de Git interviene en el Dockerfile.

Esto sustituye la prohibición anterior de copias solo para el árbol generado por
Go; sigue prohibido mantener copias manuales o `replace ../rac-platform` en
producción. El costo es un checkout mayor (aproximadamente 45–48 MiB de vendor
por servicio con las dependencias actuales); evita infraestructura adicional de
distribución y permite builds independientes. No se introduce un proxy privado
sin un servicio que pueda operarlo y autenticarlo correctamente.

## Actualización reproducible

Con Go de la versión de `go.mod` y acceso SSH propio, configurar `GOPRIVATE` para
`github.com/cazocarma`, descargar la versión publicada y ejecutar:

```sh
go get github.com/cazocarma/rac-platform@v0.3.0
go mod tidy
go mod vendor
go vet ./...
go test -race ./...
```

El transporte Git debe usar SSH o un gestor de credenciales, sin tokens en URLs,
Dockerfiles, argumentos de build o archivos versionados. La descarga inicial en
este entorno usó un contenedor desechable, llave montada de solo lectura,
known_hosts verificado y copia de trabajo de la llave en tmpfs; no en una capa.

Commit incluirá go.mod, go.sum y vendor juntos. Infra actualiza los SHAs completos
de platform y consumidores en `ci/companion-revisions.json`. El gate
`scripts/check_go_vendor.py` compara los paquetes privados generados con el
checkout fijado de platform y detecta modificaciones u omisiones de archivos.
La consistencia de módulos se comprueba también al compilar con Go.

Para versiones nuevas de cualquier dependencia hay que regenerar todo vendor,
no editarlo a mano. El vendoring no sustituye la revisión de licencias,
actualizaciones o análisis de vulnerabilidades de las dependencias.

Referencia: [Go Modules Reference — Vendoring](https://go.dev/ref/mod#vendoring).
