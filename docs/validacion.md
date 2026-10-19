# Validación del 15 de octubre de 2026

> Diagnóstico/preparación inicial. Ver [implementación vigente](implementacion-oidc.md) para los cambios posteriores.

## Ramas y configuración

- Verificadas por `git ls-remote --heads origin dev qa prd` las tres ramas de
  cada repositorio. SHA local y remoto coinciden; seguimiento configurado;
  todos los checkouts están en `dev`. Ver `ramas-verificadas.md`.
- DEV, QA y PRD pasan `docker compose config --quiet` con sus respectivos
  archivos. QA/PRD se validaron con valores sintéticos ignorados por Git.
  No se descargaron imágenes de aplicación ni se desplegaron QA/PRD.
- QA/PRD no tienen `build`, seeds demo ni puertos publicados de PostgreSQL o
  RabbitMQ. Requieren valores de secretos e imágenes antes de poder arrancar.
- DEV construyó auth, usuarios, match y Flutter desde los checkouts `dev`.
- Makefile verificado desde PowerShell y Git Bash, incluyendo la delegación
  desde la carpeta padre. ENV inválido y plantilla PRD sin secretos se rechazan.
- Bootstrap de PostgreSQL probado en un contenedor aislado con datos en tmpfs:
  crea base `keycloak`, rol y esquema `kc`; repetir el bootstrap conserva todo.
  No se modificaron los datos del PC.
  El SQL de aplicación también se probó desde cero: crea availability, pero
  faltan las dos columnas timestamp de sesión; hallazgo confirmado.

## Pruebas de código

Ejecutado `go test ./...` para cada servicio en `golang:1.24-alpine`, con
fuentes montadas en solo lectura y caches de compilación en volúmenes separados.

| Repositorio | Resultado |
| --- | --- |
| auth | Exit 0; todos los paquetes reportan `no test files` |
| user | Exit 0; todos los paquetes reportan `no test files` |
| match | Exit 0; todos los paquetes reportan `no test files` |
| chat | Exit 1; archivos `.go` vacíos: `expected 'package', found 'EOF'` |
| payment | Exit 1; mismo problema |
| alert | Exit 1; mismo problema |
| admin | Exit 1; mismo problema |

No se agregaron tests para ocultar estos fallos ni se implementaron los esqueletos.
Un Dockerfile que solo compila `./cmd/server` puede construir el servidor mínimo
de health aunque `go test ./...` falle al recorrer los paquetes vacíos.

Flutter: imagen web construida correctamente; `flutter pub get` + `flutter test`
ejecutados en una copia temporal dentro del contenedor, sin cambiar el lockfile
del repositorio. Test falla al resolver `package:app/main.dart` y el constructor
`MyApp`; el único test sigue siendo el contador de plantilla.

## Comprobaciones de ejecución DEV

`make check` devuelve éxito: frontend HTTP 200; auth, user y match health HTTP
200; skills responde el catálogo. Login API con `cliente1` recibe token,
pero falta `ok=true` que el consumidor Flutter exige. `/api/auth/register`
devuelve HTTP 404. No se afirma que el login de la interfaz funcione.

Se preservaron los volúmenes previos. Consulta a `information_schema.columns`
confirma que el volumen de este PC no tiene `usuario.fecha_nacimiento` ni
`sesion.creado_en`/`actualizado_en`. Por eso health verde no valida perfil ni
reservas. No se ejecutaron migraciones ni se borraron volúmenes.

Los logs de compilación y del test Flutter quedan en la carpeta padre local
(`rac-build-dev.log`, `rac-flutter-test.log`, `rac-start-dev.log`), fuera de los
repositorios. No contienen tokens del login; esa comprobación solo imprimió
booleanos. El informe registra resultados, sin copiar secretos.

## Límites

No se hizo validación móvil, carga, análisis exhaustivo de vulnerabilidades,
prueba completa de OAuth social ni reserva end-to-end. Tampoco se ensayaron
backups, restauración, TLS, entrega CI/CD o recuperación de un host. QA/PRD
están preparados estructuralmente; no son versiones certificadas para uso real.
