# P08 — Revisiones de publicaciones

Estado: base local en desarrollo sobre P07. La CI del PR P07 #12 terminó completa
en SUCCESS (run 41467621049). P08 no está publicado ni conectado a endpoints o
pantallas; la publicación anterior de la app no se considera una revisión humana.
No se activa la migración en DEV por inferencia de los ensayos desechables.

## Modelo preparado

`rac-user-service/internal/listings` prepara un snapshot completo y separado del
perfil privado: nombre, biografía, intereses, descripción, actividades/notas,
precio entero CLP, referencia de foto inmutable y área pública seleccionada.
El área no se copia desde la ciudad privada. Los identificadores admitidos y
precios requieren una política explícita: las cifras y áreas de pruebas son
sintéticas, no aprobación de D04 ni datos CUT inventados.

El preparador ordena/normaliza colecciones, calcula SHA-256 sobre JSON UTF-8
canónico propio (versión `rac-listing-payload/1`) y congela copias de payload y
evaluación. Conserva la versión de política de publicación y de analizador/léxico
por campo; cambios de versión durante una evaluación, cancelación, puntuación
inválida, spans inválidos o exceso de presupuesto fallan antes de persistir.
Contacto produce un error corregible sin fragmentos/reglas privados. Las demás
señales calculan prioridad, nunca aprobación o sanción. Una categoría no evaluada
se conserva como tal, incluso con riesgo cero.

## Persistencia

V041 agrega `listings`, `listing_revisions` y `listing_revision_decisions`.
El texto canónico es la fuente; JSONB y digest se generan en PostgreSQL sin
permitir que un servicio suministre un hash falso. El historial y decisiones son
append-only, también frente a escrituras ordinarias del migrador. Los punteros
compuestos no pueden referenciar otra publicación; publicar exige una decisión
de aprobación registrada. Decidir bloquea la misma fila que enviar una propuesta,
rechaza autorrevisión/versión desplazada y exige despejar el pendiente en la misma
transacción. Nueva propuesta y rechazo conservan el puntero publicado anterior.

Las filas antiguas reciben solo un sobre `unpublished`, sin certificar su texto
ni borrar habilidades retenidas. Un sobre sin historia puede desaparecer con el
perfil; una revisión existente requiere la futura saga auditada P12 para purgarse.
No se ha activado una retención irreversible de datos reales.

`listings.Submit` usa la transacción del dueño y verifica pertenencia por subject,
versión esperada y hash. Hace análisis fuera del bloqueo. Obtiene el siguiente
número en otra sentencia después de adquirir el lock para evitar un max obsoleto
tras esperar bajo READ COMMITTED. No hace commit: el servicio debe incorporar
auditoría/outbox y comprobar documentos, identidad y standing antes de confirmar.
Un error exige rollback de toda la operación.

## Evidencia local

Pruebas del preparador con el analizador compartido real: contacto por superficie,
ofuscación, sospecha que sigue a revisión, hash canónico, copias inmutables,
catálogo cerrado, precios inclusivos, versiones/cancelación, presupuesto y medios
externos. Se ejecutan con Go 1.27.2 y `-race`.

El ensayo de permisos pasó desde BD nueva y actualización V018 con
migrador real sin superusuario, incluyendo digest UTF-8, historial inmutable,
autorrevisión, revisión obsoleta y conservación de la aprobada
(`.local/p08-listing-database-permissions-final.log`, exit 0). Incluyó restaurar
dos revisiones/decisiones y sus digests, y rechazar punteros entre publicaciones.
El ensayo Go sobre PostgreSQL real pasó con escritura como `rac_user`, pertenencia,
rollback conjunto y dos envíos concurrentes sobre una versión
(`.local/p08-listing-migrations-user.log`, exit 0).
El conjunto se repitió desde snapshots Git fijos de infra `bd6178b`, user
`ded480c`, platform `5f1030f` y los demás pins candidatos: permisos/restauración y
migraciones/user terminaron exit 0
(`.local/rac-p08-db-proof-3d2b203f09a2/{revisions.json,permissions.log,migrations-user.log}`).
Los cinco servicios pasaron vet y `-race` con v0.15.1
(`.local/p08-rac-*-go-v0151.log`).

La auditoría de rutas además cerró una omisión P07 en POST `/api/user/profile`
y verificó los datos públicos guardados antes de ambas publicaciones, incluidos
nombres heredados del login. Ese guard conserva `FOR NO KEY UPDATE` para no
reintroducir el bloqueo FK contra sanciones. Tiene prueba PostgreSQL específica
de nombre/bio/intereses almacenados, rollback y publicación tras corrección;
se registra por separado después del primer snapshot para no atribuirle evidencia
de un código anterior.

Esa segunda prueba terminó exit 0 desde infra `72b70fb` y user `6475294`, con
platform v0.15.1 y el resto de pins fijos
(`.local/rac-p08-db-proof-6971df4067ff/{revisions.json,migrations-user.log}`).
Se exigió el PASS de `TestStoredPublicContactPostgres`: nombre, biografía e
intereses guardados se rechazan antes de crear un perfil por ambas rutas, y una
cuenta corregida con teléfono privado puede publicar. La suite de migraciones
también mantuvo adopción legacy, preservación, checksums, documentos y standing.
Todo ocurrió en contenedores desechables; los scripts retiraron sus recursos.

## Corte pendiente para completar P08

1. API dueña de envío/lectura/decisión, autorización staff MFA/step-up y razones
   versionadas; auditoría/eventos en la misma transacción. Una fila de decisión
   SQL no prueba por sí sola que un humano autorizado la emitió.
2. Revalidación de standing, identidad, documentos, catálogo y foto/política
   efectiva al aprobar, con carreras entre dos instancias y rollback completo.
3. Corte coordinado de TODAS las lecturas públicas, descubrimiento y medios a
   snapshots aprobados, y retirada de rutas mutables alternativas. Cambiar un
   nombre, biografía o foto no puede alterar una publicación ya aprobada.
4. Flujo Flutter de envío/estado/cambios y consola de cola, sin plazos prometidos
   mientras D07 no los defina. No usar "Publicar" para un envío a revisión.
5. Resolver referencias de foto/P09 antes del corte: cambiar/borrar una foto
   personal no puede sustituir un objeto aprobado ni dejar una URL pública viva.
6. Laboratorio integrado y matriz de autorización de cada ruta, versión obsoleta,
   rechazo, retirada de categoría, política de precio, KYC/standing y medios.

P07 aún necesita corpus humano, paridad de reglas públicas, política/léxico
persistidos y hot reload. Se reprodujo un defecto previo a ese reload: `New`
retenía el slice original y una mutación podía retirar `minors` de la lista no
evaluada sin agregar reglas reales. También aceptaba pesos NaN y dependía de una
lista pública mutable de categorías. La corrección publicada v0.15.1 (`5f1030f`)
congela las reglas, aísla categorías internas y rechaza pesos no finitos.
Reproducción fallida en `.local/p07-lexicon-snapshot-reproduction.log`; suite
completa con `-race` y caso concurrente pasaron en
`.local/p07-lexicon-snapshot-final.log`. No se reescribió v0.15.0.
