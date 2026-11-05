# ADR-011 — foto revisada y promoción ligada a la publicación

Estado: implementación parcial: V048 liga el envío al resultado inmutable y
V049 prepara la [previsualización privada](P09-private-preview.md); V050 fija
[intentos auditados antes de I/O](P09-promotion-intents.md). No se activaron flags.
La copia y readback exactos ya se prueban desde el intento confirmado. La
integración/recibo durable/finalización, visibilidad pública y retirada siguen pendientes.
Complementa ADR-002 y M4/M6. No modifica las decisiones de negocio/jurídicas
D04–D14, no habilita flags ni cambia el snapshot público actual.

## Invariantes que debe cumplir la implementación

1. La preparación V047 produce una fuente privada y un resultado procesado
   inmutables. `awaiting_review` no significa aprobación de foto o publicación.
   Un resultado `contact_correction_required` no puede promoverse por una ruta
   alternativa; requiere otra imagen corregida.
2. El envío de publicación debe ligar su referencia de foto a un resultado
   procesado exacto, propio y disponible. El cliente no elige URL, key, hash,
   MIME de salida o aprobación. El vínculo pertenece a la revisión inmutable,
   no a `usuario.foto_clave` ni a «la última foto» mutable del usuario.
3. El equipo ve el JPEG saneado exacto que se evalúa, junto al snapshot textual
   y sus señales privadas. Solo una revisión vinculada y autorizada permite
   previsualizarlo; no existe un explorador general de originales de usuarios.
   Cada acceso se audita antes de entregar bytes, con actor verificado y MFA.
4. La decisión humana debe aprobar la revisión correspondiente. Una preparación
   correcta o una decisión de imagen aislada no publica el perfil ni concede
   identidad/edad verificada. Autorrevisión/aprobación y tokens corrientes quedan
   denegados por la misma frontera staff de P08.
5. El destino `public-media` sigue privado y separado de cuarentena, staging y
   avatares. La copia nunca debe producir un objeto anónimamente accesible.
   La promoción se vincula a la aprobación de la revisión, no al upload.
6. Copiar/verificar S3 no ocurre bajo locks de una transacción de negocio larga.
   Antes de I/O se persiste un intento/intent con clave propia y referencias
   exactas de revisión, versión/hash, fuente/digest, política y comando humano.
   Una respuesta incierta conserva esa referencia y sus objetos para reconciliar.
7. La finalización verifica los bytes copiados, VersionId y digest, y vuelve a
   comprobar revisión pendiente, versión/hash, autor distinto, MFA vigente,
   standing, documentos/assessment, identidad cuando corresponda, catálogo,
   foto y política. Un cambio o vencimiento impide publicar aunque exista una
   copia privada. Retry exacto tras ACK perdido es idempotente; comando distinto
   no puede apropiarse de otro intento.
8. El commit guarda conjuntamente decisión/auditoría/outbox, referencia del medio
   verificado y puntero público de la revisión. No se altera el contenido/hash
   del snapshot para sustituir la foto después de aprobarlo.
9. Catálogo, detalle y recursos públicos usan una sola regla de visibilidad:
   revisión aprobada vigente, cuenta/categorías permitidas y medio disponible.
   Nombre/bio/foto ya aprobados nunca se reconstruyen desde el perfil mutable.
   Las rutas legacy no pueden quedar como bypass del corte público.
10. Las URLs tienen firma, propósito y vencimiento corto explícitos, sin PII.
    Su resolución debe comprobar autorización y disponibilidad actual; no se
    puede usar una URL pública para leer previews u originales. La retirada de
    un medio invalida sus publicaciones y nuevas resoluciones. Un objeto que
    llegó a leerse antes no puede prometerse «borrado de la memoria» del visitante.
11. La baja física, retención, legal hold y evidencias se coordinan con P10/P12;
    no hacer DELETE compensatorio de un objeto cuyo commit quedó incierto.
    No aplicar WORM indiscriminadamente a fotos públicas/personales.
12. El catálogo de pHash retirados debe tener procedencia de caso/evidencia
    autorizada. El constructor que valida solo forma UUID no demuestra esa
    procedencia. Sin catálogo configurado la similitud permanece no evaluada;
    no se transforma la ausencia de configuración en una aprobación limpia.

## Fronteras y pruebas de salida

User conserva publicaciones, fotos y visibilidad. Admin presenta la consola y
proxy fijo de staff; no obtiene SQL de user ni admite destinos de proxy del
cliente. Nuevas funciones privadas deben conservar logins function-only y el
verificador de grants de P02/P08. La identidad de promoción solo necesita Get
de staging y creación/readback del destino autorizado, sin administrar buckets,
leer originales o retirar evidencias.

Probar: fuente de otro dueño, fuente sin confirmar/procesar, contacto OCR,
revisión superseded, cambio de política, restricción/consentimiento/MFA durante
la copia, S3 ACK perdido, dos aprobadores concurrentes, commit fallido, retry
exacto/conflictivo, retirada y acceso por URL vieja, acceso directo sin audiencia
o permiso, edición del avatar tras aprobación, catálogo retirado y fuga de rutas
legacy. Incluir API real, IAM real y navegador en web/anchos móviles. No cerrar
P08/P09 solo porque una de sus pruebas de componente esté verde.
