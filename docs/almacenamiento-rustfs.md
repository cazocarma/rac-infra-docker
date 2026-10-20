# RustFS: laboratorio S3 de DEV

## Decisión de arquitectura

RustFS es infraestructura externa a la aplicación, como PostgreSQL o RabbitMQ.
Su imagen, volúmenes y operación pertenecen a rac-infra-docker. No se crea otro
repositorio ni se copia el código de RustFS. rac-user-service sigue siendo dueño
de las fotos de perfil: autorización, normalización, publicación y metadatos.

Un servicio de archivos propio tendría sentido si varios dominios necesitan
adjuntos con reglas compartidas (cuotas, antivirus, retención, moderación o
procesamiento asíncrono). Usar S3 por sí solo no exige ese servicio adicional.
Las credenciales administrativas nunca deben llegar a Flutter.

## Alcance actual

Laboratorio independiente rac-dev-storage con RustFS 1.0.3 fijado por digest,
buckets privados por defecto y volúmenes rustfs-data / rustfs-logs. API y consola
solo escuchan en loopback del host. No modifica QA/PRD ni el stack principal.
**Las fotos reales aún usan profile-photos; no se han migrado a RustFS.**

Este despliegue tiene un solo nodo y disco, sin redundancia. Recrear un contenedor
conserva el volumen; borrar el volumen o perder el disco pierde sus datos.
No hay respaldos automáticos todavía. El laboratorio usa credenciales raíz
únicamente para sus pruebas; la futura aplicación deberá usar una identidad
restringida a su bucket, nunca estas credenciales administrativas.

## Uso desde rac-infra-docker

1. Ejecutar `python scripts/init_storage.py` con Python 3. Crea envs/.env.storage
   con secretos aleatorios y no sobrescribe credenciales existentes. El archivo
   está ignorado por Git; en Windows sus permisos dependen de la ACL del usuario.
2. `make storage-up` inicia y espera la comprobación de salud.
3. Abrir http://localhost:9001/rustfs/console/ e ingresar los valores del archivo local.
   La API S3 queda en http://localhost:9000.
4. `make storage-test` verifica creación de bucket, subida, descarga e integridad,
   metadatos, rechazo anónimo, URL firmada y borrado. Limpia sus objetos y bucket.
5. `make storage-test-persistence` además escribe una prueba, recrea RustFS,
   comprueba la persistencia y limpia esa prueba. Interrumpe brevemente RustFS;
   ejecutar exclusivamente contra este laboratorio DEV.
6. `make storage-stop` detiene y elimina los contenedores, conservando volúmenes.
   `make storage-logs` muestra logs del laboratorio.

Los comandos usan Docker Compose. RustFS también documenta Podman, pero esa
ruta no se ha validado en este PC. No usar latest ni exponer estos puertos a Internet.

## Próxima integración

Agregar un adaptador S3 al servicio de usuarios, crear bucket e identidad con
permisos mínimos, probar los mismos controles de publicación/propiedad y migrar
las fotos existentes con verificación de integridad. Mantener las URLs públicas
actuales y la validación del backend; un bucket privado no reemplaza esas reglas.
El cambio de almacenamiento requiere una migración explícita de archivos; no es
una migración SQL ni basta con cambiar una variable de entorno.

## Referencias

- https://docs.rustfs.com/en/installation/container/docker
- https://docs.rustfs.com/en/installation/container/podman
- https://github.com/rustfs/rustfs

## Validacion local realizada

19 de octubre de 2026: pruebas S3 y persistencia tras recreacion completas;
contenedor saludable. Configuraciones principales DEV/QA/PRD verificadas sin
cambiar su almacenamiento. Podman y despliegue productivo no probados.
