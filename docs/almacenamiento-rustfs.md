# RustFS y fotos de perfil

## Arquitectura

RustFS se opera desde rac-infra-docker como PostgreSQL o RabbitMQ. Las reglas de
fotos pertenecen a rac-user-service: OIDC, propiedad, validacion, normalizacion,
publicacion y metadatos en PostgreSQL. No necesitamos otro microservicio para
traducir llamadas S3. Un servicio de archivos propio se evaluara cuando existan
funciones compartidas como adjuntos de chat, cuotas, antivirus o procesamiento.

La app mantiene las mismas rutas /api/user/me/photo y /api/user/media/profile/.
El backend usa AWS SDK Go v2 contra un bucket privado; Flutter no accede al bucket
ni recibe sus credenciales. Un fallo S3 produce 503, no una foto inexistente ni
un cambio silencioso a disco local. /ready incluye HeadBucket; /health permanece
como liveness. Las comprobaciones usan plazos limitados y contextos HTTP reales.

## Infraestructura DEV

RustFS 1.0.3 fijado por digest, proyecto rac-dev-storage y volumenes rustfs-data /
rustfs-logs. API http://localhost:9000 y consola
http://localhost:9001/rustfs/console/ solo publicados en loopback. La red externa
rac-dev-storage_default conecta el backend con rustfs:9000 al activar el overlay.
No se usa host.docker.internal; funciona tambien en el runner Linux de CI.

El bucket permanente es rac-dev-profile-photos. init_storage.py genera secretos
aleatorios en envs/.env.storage sin imprimirlos. configure_storage.py crea el
bucket sin politica publica y un usuario IAM separado. Su politica permite
ListBucket (requerido por HeadBucket), GetObject, PutObject y DeleteObject solo
en ese bucket. No puede crear buckets, modificar politicas ni leer otro bucket.
Las credenciales administrativas quedan exclusivamente en herramientas operativas.

## Activacion y migracion

Desde rac-infra-docker, con Python 3 y Docker Compose:

1. `make up` inicia el stack DEV.
2. `make storage-activate` inicializa secretos, inicia RustFS y configura bucket/IAM.
3. Antes del cambio construye la imagen nueva y detiene backend-user. El comando
   migrate-photos monta profile-photos como solo lectura, copia exclusivamente
   claves referenciadas en usuario.foto_clave y verifica los bytes contra S3.
4. Si falta una foto de origen, hay conflicto de destino o falla una copia, no
   activa S3 y vuelve a iniciar el servicio con su configuracion local anterior.
   Los objetos ya copiados permiten reintentar; no se sobrescriben conflictos.
5. Solo tras verificar todas las fotos promueve atomicamente el archivo privado
   envs/.env.photos-s3.pending a envs/.env.photos-s3 y recrea backend-user con el
   overlay compose.photos-s3.yaml. Este archivo contiene solo credenciales de app.
6. Si el arranque posterior falla, no regresa automaticamente a una copia local
   que pueda quedar desactualizada. Reparar RustFS/configuracion y reintentar.

Make detecta el archivo de activacion en DEV, agrega el overlay e inicia RustFS
antes de make up. Repetir storage-activate con la misma configuracion conserva las
fotos nuevas; no vuelve a migrar desde un origen antiguo. Un cambio de credenciales
requiere rotacion explicita. Todos los archivos .env mencionados estan ignorados
por Git y excluidos del contexto de construccion. En Windows dependen de la ACL
local del usuario; no compartirlos.

No cambia las claves, URLs ni el esquema SQL: V007 conserva su checksum. El origen
local no se borra; es una copia del momento del cambio, no un respaldo actualizado.
No quitar el archivo de activacion como rollback despues de recibir fotos nuevas.
Respaldar y verificar S3 + base antes de cualquier cambio de proveedor.

## Pruebas y operacion

- `make storage-test`: integridad S3, bucket privado, URL firmada y borrado.
- `make storage-test-persistence`: ademas recrea RustFS y verifica persistencia;
  interrumpe brevemente las fotos de la app si esta conectada al mismo RustFS.
- `python scripts/test_photo_storage.py`: PostgreSQL desechable migrado + RustFS
  real; pruebas HTTP de propiedad, publicacion, reemplazos simultaneos, borrado,
  fallo de escritura, migracion repetible, archivo faltante y conflicto de bytes.
- `make storage-logs` / `make storage-stop`: muestra logs / detiene RustFS sin
  borrar volumenes ni la red conectada al backend. Con S3 detenido, /ready falla.
- `make down` detiene el stack principal; RustFS se detiene por separado.

CI ejecuta la activacion S3 antes de pruebas API/navegador, ademas de probar la
migracion con una base desechable. Los fixtures usan imagenes sinteticas y se limpian.
Si Python no esta en PATH, pasar `PYTHON=ruta/al/python` a make.

## Limites pendientes

DEV tiene un nodo/disco sin redundancia y no hay respaldos automaticos. Recrear
contenedores conserva objetos; borrar volumenes o perder el disco pierde datos.
Los fallos de borrado posterior al commit se registran sin secretos. Un commit o
una escritura remota con resultado incierto puede dejar un objeto huerfano privado;
aun falta conciliacion automatica de objetos sin referencia. Nunca borrar objetos
por antiguedad sin contrastar las referencias vigentes.

QA/PRD conservan su configuracion anterior y no se han desplegado. Para usar S3 alli
se requieren endpoint con TLS, bucket e identidad independientes por ambiente,
overlay de ejecucion y migracion verificada. El adaptador ya existe, pero no se
aplican automaticamente los secretos ni el RustFS de DEV a otros ambientes.
Podman esta documentado por RustFS pero no se ha probado en este PC.

## Referencias

- https://docs.rustfs.com/en/installation/container/docker
- https://docs.rustfs.com/en/security-compliance/iam/policies
- https://docs.aws.amazon.com/sdk-for-go/v2/developer-guide/configure-endpoints.html

## Evidencia local del cambio

19 de octubre de 2026: activacion DEV completa y backend saludable con S3. Habia
cero fotos referenciadas en la base DEV al cambiar; el volumen original se conserva.
Se probaron migraciones no vacias con archivos sinteticos en una base desechable,
asi como conflictos, falta de origen y repeticion sin duplicados.

Go vet y go test -race completos; pruebas HTTP sobre RustFS y PostgreSQL desechable;
API real OIDC/reservas/cupos/notificaciones; navegador escritorio/movil con carga,
privacidad previa a publicacion, recreacion de backend, lectura publica y borrado.
DEV/QA/PRD config y reglas de promocion verificadas. No se desplego QA/PRD.
