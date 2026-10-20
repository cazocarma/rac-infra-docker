# Respaldos automaticos DEV

## Que esta configurado

Contenedor backups, sin socket Docker, con Restic 0.19.1 y copias cifradas en un
directorio del host independiente de los volumenes fuente:
RAC/.local/backups/rac-dev/repository. Se ejecuta una vez al activar y despues
cada 24 horas. Tras reiniciar, detecta si hay una copia vencida. Necesita Docker
encendido; no ejecuta tareas si el PC esta apagado. Reintenta fallos cada 5 minutos.

Retiene 7 copias diarias, 4 semanales y 3 mensuales segun la politica de Restic;
no es la suma exacta de snapshots, porque una copia puede cubrir varias categorias.
Solo aplica retencion tras crear una copia y comprobar el repositorio. Ejecuta
restic check antes y despues de forget/prune. Una falla no elimina el repositorio.

Incluye:

- pg_dump custom de RAC con snapshot exportado y consistente.
- Solo fotos referenciadas en ese snapshot, descargadas por API S3, no archivos
  internos del volumen RustFS. Se registran hashes SHA-256 y claves en el manifiesto.
- pg_dump custom independiente de Keycloak y pg_dumpall --globals-only para roles.
  Los roles incluyen hashes de contrasena, por eso se almacenan dentro del cifrado.
- Manifiesto con conteos de usuarios, reservas y resenas, archivos y hashes.

No incluye mensajes pendientes de RabbitMQ, el sistema operativo ni archivos de
secretos .env. Conservar estos y el password de Restic por separado en un lugar
seguro; sin el password no se puede recuperar el repositorio. No pegarlos en chats.
Los archivos .env estan ignorados por Git y excluidos del contexto Docker.

## Consistencia de fotos

Las escrituras y la migracion de fotos toman el lock transaccional compartido (726224,1). El
respaldo toma el exclusivo antes de abrir su snapshot repeatable-read y mantiene
ese bloqueo hasta copiar dump y fotos. Asi no se sustituye ni elimina una foto
referenciada mientras se copia. Los cambios de foto pueden esperar durante esa
fase; las reservas y lecturas siguen funcionando. El bloqueo se libera al terminar
o desconectarse. No copiar un volumen de Postgres/RustFS en caliente como archivos.

RAC y Keycloak se respaldan como bases independientes y no tienen un snapshot
global atomico entre ellas. La restauracion prueba ambas bases y objetos; no
certifica una recuperacion completa de toda la plataforma con sesiones activas.

## Credenciales y ejecucion

El agente recibe el acceso Postgres necesario para dumps/roles y una identidad S3
exclusiva de solo lectura del bucket de perfiles. No recibe la raiz de RustFS.
La preparacion IAM comprueba que esa identidad no pueda escribir objetos.
La preparacion host usa UID/GID actuales en Linux y guarda la clave de Restic en
envs/.env.backups con permisos privados; Windows depende de la ACL del usuario.
El staging y las restauraciones descifradas se realizan en tmpfs y no en el host.
El area de trabajo tiene un limite de 512 MiB: si los datos lo superan hay que
reconfigurar ese recurso; el respaldo falla en lugar de llenar el disco del host.
La conexion que protege el snapshot limita la inactividad transaccional a 120 s
y cada comando externo a 10 minutos. Dimensionar estos limites antes de crecer.

Comandos desde rac-infra-docker (Python 3 para inicializar y probar restauracion):

- make backup-enable: configura, hace una copia e inicia la programacion DEV.
- make backup-now: copia inmediata con el mismo bloqueo, cifrado y retencion.
- make backup-status: ultima copia correcta, fallo y cantidad de fotos.
- make backup-restore-test: restaura latest en PostgreSQL y RustFS desechables.
- make logs SERVICE=backups: eventos JSON sin contrasenas ni contenido de usuarios.

Si Python no esta en PATH, pasar PYTHON=ruta/al/python a make. Una vez habilitado,
make up incluye el agente; make stop/down lo detiene junto con la app. Los datos
del repositorio se conservan al eliminar contenedores/volumenes fuente. No eliminar
el directorio de copias. Cambiar BACKUP_DIRECTORY en envs/.env.backups requiere
mover/verificar deliberadamente el repositorio cifrado antes de recrear el agente.

El healthcheck requiere una copia correcta de menos de 26 horas y ningun fallo
pendiente. El estado y los logs permiten observar fallos localmente; todavia no
se envia email ni hay alertas externas de perdida de respaldos.

## Prueba de recuperacion

scripts/test_backup_restore.py crea recursos con nombres aleatorios y tmpfs,
sin publicar puertos. Restaura roles y ambas bases, compara conteos del snapshot,
comprueba las referencias de fotos y las vuelve a subir a un RustFS nuevo,
comparando sus hashes. Rechaza destinos sin el nombre exacto de fixture; nunca
restaura sobre los contenedores DEV existentes. Los recursos se eliminan al salir.

La prueba de navegador de resenas produce una foto sintetica referenciada y una
resena, respalda mientras el fixture existe y comprueba esa recuperacion. CI corre
esa misma ruta. La imagen de app necesita incluir el lock de fotos antes de
activar backups; make up primero en una instalacion nueva.

Para una recuperacion real se necesitara detener escrituras, elegir un snapshot,
restaurar en destinos nuevos, recuperar secretos externos, reprovisionar IAM S3,
comprobar referencias, arrancar las imagenes/contratos correspondientes y recien
entonces cambiar endpoints. No se ofrece un comando destructivo contra DEV.

## Limites

Esta copia local protege frente a errores en datos/volumenes fuente, pero el PC
sigue siendo un punto unico de falla. Falta una segunda copia fuera del equipo
(disco externo u otro proveedor), alertas externas y ensayos periodicos de la
recuperacion completa. QA/PRD no se desplegaron ni reciben secretos de DEV.
Los objetos huerfanos no referenciados no se respaldan; aun falta su conciliacion.

Referencias: https://www.postgresql.org/docs/16/app-pgdump.html,
https://www.postgresql.org/docs/16/app-pg-dumpall.html,
https://restic.readthedocs.io/en/stable/060_forget.html.
