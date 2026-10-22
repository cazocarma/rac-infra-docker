# ADR-002 — Publicaciones con revisiones y revisión previa

Estado: dirección técnica aprobada; D04/D05/D06/D09 pendientes.

## Propuesta

User será dueño de `listings`, `listing_revisions`, `activity_categories` y `compa_activities`. Listing: unpublished/published/suspended/removed. Revisión: draft/submitted/approved/rejected/changes_requested/superseded; una revisión enviada congela el payload y su hash. Editar crea una nueva revisión; aprobación referencia exactamente la versión evaluada, sin modificar su contenido.

El snapshot público contiene nombre visible permitido, descripción, actividades versionadas, tarifa entera CLP, referencia a versión de foto aprobada, ciudad/comuna y datos necesarios de disponibilidad. No resolver nombre/bio/foto desde el perfil mutable actual al servir el catálogo. Las reseñas se moderan por separado; no permiten inyectar contenido en un snapshot aprobado. Foto eliminada/suspendida invalida su publicación mediante una transición trazable, sin reutilizar el mismo object key.

Al aprobar: transacción/optimistic lock sobre revisión y standing vigente, KYC approved/adult, aceptaciones requeridas, categorías activas, foto aprobada y política efectiva. Impedir aprobar mientras se suspende la cuenta; invalidaciones posteriores bloquean la lectura pública aunque el trabajo asíncrono de ocultación siga pendiente. GET catálogo, detalle, búsqueda y medios deben usar una única política de visibilidad. No filtrar solo en Flutter.

Catálogo cerrado; sin habilidades libres ni búsqueda libre de descripción. Propuesta del prompt: cine, teatro, conciertos, museos, running, trekking, ciclismo, juegos de mesa, karaoke, conversación de idiomas, fotografía urbana y restaurantes. D04 debe aprobar actividades y lugares; no habilitar salud, transporte, cuidado de menores ni servicios sexuales. Máximo cinco configurable. Geografía normalizada a comuna sin direcciones exactas.

La migración mapeará habilidades conocidas a categorías aprobadas; las no mapeables quedan no publicadas para revisión, nunca eliminadas suponiendo que DEV no tiene datos. Inventariar y retirar todas las rutas alternativas actuales de publicación/perfil/habilidades en el mismo corte coordinado de frontend/API/contratos. Conservar versiones históricas de política y relaciones necesarias para reservas previas.

## Medios

Quarantine privada → magic bytes/límites/reencodificación sin EXIF → pHash y OCR local → señales → revisión humana → bucket `public-media` privado → URL firmada breve y versionada. El nombre del bucket no implica acceso anónimo. Credenciales por bucket y operación, URLs sin PII y sin logs de firma. Cambiar la foto personal no modifica la foto de la revisión ya publicada.

Clasificación externa de imágenes desactivada. pHash es señal, no prueba de identidad ni detector infalible de recortes. Rostro obligatorio depende de D09: `require_face_in_photo=false` no puede acompañarse de una instrucción UI que exija rostro. Nuevas revisiones no sustituyen la versión aprobada hasta la decisión; una medida de seguridad puede ocultar la publicada.

## Pruebas y consecuencias

Edición concurrente, aprobación obsoleta, ban durante aprobación, foto nueva sin aprobar, referencias directas a medios, revisión rechazada por API alternativa, categoría retirada, precio fuera de límites, enum desconocido y ACL S3. Un reporte no basta por sí solo para una sanción irreversible. D06 resolverá la suspensión preventiva automática frente a reportes abusivos. Revisores humanos y cola operativa son requisitos reales, no solo estados de BD.
