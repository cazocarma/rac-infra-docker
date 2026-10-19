# RAC: infraestructura y entornos

Orquestación y documentación general de Rent-A-Compa.

La guía actual está en [docs/README.md](docs/README.md), con el estado real de
los 11 repositorios, ramas, hallazgos y operación de DEV/QA/PRD.

## Desarrollo

Clonar los repositorios como carpetas hermanas dentro de RAC/. Desde este repo:

```sh
make up
make ps
make check
make logs SERVICE=backend-match
make stop
```

DEV es el entorno predeterminado. Antes de una instalación nueva, copiar
`envs/.env.dev.example` a `envs/.env.dev` y
`envs/realm.dev.example.json` a `envs/realm.dev.json`.

## QA y PRD

Leer [ambientes](docs/ambientes.md) y [pendientes](docs/pendientes.md) antes de
preparar otro host. Configuración e imágenes son independientes por entorno:

```sh
make ENV=qa config
make ENV=prd config
```

Estos comandos necesitan sus archivos locales de variables. Las plantillas
contienen campos obligatorios vacíos. QA/PRD no fueron desplegados; quedan
bloqueos de contratos, migraciones y entrega por resolver.
