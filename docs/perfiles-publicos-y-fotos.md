# Perfiles públicos, biografía y fotos

## Comportamiento

Mi perfil permite editar una biografía de hasta 600 caracteres y elegir una foto desde la galería. La foto tiene confirmación visual antes de enviarla, se guarda por separado y puede quitarse. La vista previa muestra los cambios del formulario sin guardarlos ni activar el perfil compa. Foto, nombre, biografía e intereses se usan en la presentación pública; correo, teléfono y ubicación personal no se incorporan a esa respuesta.

Un usuario base puede guardar su foto para preparar la presentación. La imagen solo se sirve públicamente cuando existe un perfil compa publicado. El catálogo y el detalle compa usan exclusivamente las URLs de imágenes generadas por RAC. La descripción de servicios, habilidades, tarifa y disponibilidad siguen en el perfil compa, separadas de la biografía personal.

## Imágenes y API

El propietario se obtiene siempre del token OIDC verificado. `PUT /api/user/me/photo` recibe bytes JPEG/PNG, no rutas ni URLs. El límite es 5 MiB; cada lado debe medir entre 32 y 4096 píxeles, con un máximo de 12 millones de píxeles. El servidor verifica formato y dimensiones antes de decodificar, corrige orientación EXIF, recorta al centro, aplana transparencia y genera un JPEG nuevo de 512×512. No se conservan EXIF/GPS ni contenido agregado al archivo original. Hay dos cargas/procesamientos simultáneos por instancia; el exceso recibe 429. El servidor limita el tiempo de lectura de la petición a 30 segundos.

`GET /api/user/me/photo` requiere autenticación y permite consultar la foto propia antes de publicar. `DELETE /api/user/me/photo` es idempotente. El servidor genera nombres aleatorios de 128 bits, nunca utiliza el nombre original y solo permite claves con formato controlado. La ruta pública `/api/user/media/profile/<clave>.jpg` comprueba la publicación y referencia actual en base de datos; las versiones sustituidas o eliminadas dejan de resolverse. Las respuestas de imagen usan no-store y nosniff.

El reemplazo/eliminación bloquea la fila propietaria en una transacción. El objeto nuevo se persiste antes de cambiar la referencia (en el adaptador local se escribe, sincroniza y cierra). Tras confirmar se retira el anterior. Los errores de validación o escritura conservan la referencia previa. Si falla la confirmación de una transacción con resultado incierto, se conserva el archivo nuevo para evitar una referencia rota; pueden quedar archivos huérfanos inaccesibles que requieren conciliación operativa. Los fallos al retirar un archivo se registran como profile_photo_cleanup_failed sin exponer rutas o datos del usuario.

## Infraestructura y migración

V007 agrega biografia y foto_clave en usuario, con límites de longitud/formato. Las migraciones anteriores mantienen sus checksums. Las antiguas columnas foto_perfil/foto_url con URLs arbitrarias no alimentan las nuevas imágenes públicas.

Compose monta profile-photos en /var/lib/rac/photos, separado automáticamente por el nombre de proyecto rac-dev / rac-qa / rac-prd. El servicio se ejecuta como usuario sin privilegios y los archivos quedan fuera del webroot. Ese adaptador local se mantiene para compatibilidad y como origen de migracion. DEV activa ahora RustFS mediante compose.photos-s3.yaml: bucket privado, identidad restringida y API con las mismas URLs. Ver [operacion S3](almacenamiento-rustfs.md).

El volumen sobrevive a recrear contenedores y a make down. Debe respaldarse y restaurarse junto con la base de datos, verificando la correspondencia entre foto_clave y archivos; DEV ya tiene [respaldos cifrados diarios y prueba de restauración](respaldos-automaticos.md). No usar down -v para conservar datos. RustFS usa su propio volumen persistente; debe respaldarse junto con PostgreSQL. El despliegue DEV sigue siendo de un solo nodo/disco y no ofrece alta disponibilidad. No se desplegó QA/PRD con este cambio.

## Validación

Pruebas Go verifican formato real, tamaño/dimensiones, re-encode, privacidad antes de publicación, propietarios, fallos de escritura, reemplazos simultáneos, eliminación y retirada de archivos. Se ejecutan con detector de carreras y PostgreSQL desechable migrado. Se usa el contexto HTTP de la petición para las transacciones, evitando retener un contexto Gin reutilizable.

Flutter comprueba la vista previa con cambios sin guardar, exclusión de contacto y rechazo de URLs de imagen externas. El navegador usa una imagen sintética y una identidad DEV desechable para guardar biografía/foto, recrear backend-user, recuperar la foto, activar como compa, ver la presentación pública en escritorio/móvil y eliminarla. Los fixtures no contienen fotos de personas y se limpian al terminar. Las comprobaciones web con tamaño móvil no sustituyen la prueba de galería/login en teléfonos físicos, que sigue pendiente.

Referencias: [OWASP File Upload](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html), [volúmenes Docker](https://docs.docker.com/engine/storage/volumes/), [procesamiento y orientación con imaging](https://github.com/disintegration/imaging).
