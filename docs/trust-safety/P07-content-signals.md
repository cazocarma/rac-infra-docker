# P07 — Analizador compartido y contactos públicos

Estado: implementación local en curso. No hay activación de detectores privados,
cola P08, sanción automática ni análisis servidor del chat privado.

## Dirección aprobada

[Decisiones del 2 de noviembre](decisions-2026-11-02.md): diccionario versionado
inicial para señales de revisión; contacto público como rechazo corregible.
La semilla no equivale a corpus curado ni a una determinación de ilicitud.
Las categorías vacías siguen no evaluadas.

## Módulo y dependencia

El motor de `rac-platform/contentsignals` existente normaliza/evalúa y devuelve
versiones, reglas y spans para revisión autorizada. La API nueva
`ContainsPublicContact` reutiliza exclusivamente el detector público: no carga
el léxico propuesto ni convierte sus señales en denegaciones comerciales.
Errores por cancelación o límite de entrada deben detener la escritura.

Se publicó el tag inmutable v0.15.0 en
`bb7522deed8ec129a761d34f23b2979afc048aa5`. El script existente
`scripts/vendor_platform.py v0.15.0` genera go.mod/go.sum/vendor de los cinco
consumidores desde ese tag, sin credenciales privadas dentro de Docker.
El push atómico de la rama `feat/content-signals` y el tag terminó correctamente
después de las pruebas locales del módulo; no se fusionó main.

## Integración user-service y Flutter

- PUT `/api/user/me`: nombre, biografía e intereses públicos; el teléfono privado
  se conserva y no se envía al detector.
- PUT `/api/user/me/compa`: descripción y notas de actividades.
- POST `/api/user/compas`: también valida la descripción, para que la ruta
  alternativa no eluda la regla.
- Rechazo 400 `public_contact_not_allowed` con identificador fijo del campo,
  sin fragmentos, reglas privadas, scores ni texto original en la respuesta.
- Fallo de análisis: 503 `content_check_unavailable`; no escritura permisiva.
- Validación antes de abrir transacción; no cambia standing ni crea una sanción.
- Flutter conserva un código tipado y muestra instrucciones es/en para corregir
  el formulario, sin perder el borrador ni iniciar refresh/reintento automático.
  El teléfono privado se distingue expresamente del contacto publicado.

## Comprobaciones

`rac-platform`: Go 1.27.2, `go vet ./...` y
`go test -race -count=1 ./...` pasaron localmente después de agregar la API.
Las pruebas incluyen contactos ofuscados, cancelación, tamaño máximo y texto
que activa léxico privado sin ser una infracción de contacto.

`user-service`, `match-service`, `chat-service`, `alert-service` y `admin-service`:
`go vet -mod=vendor ./...` y `go test -mod=vendor -race -count=1 ./...` pasaron.
`scripts/check_go_vendor.py` confirmó la fuente compartida exacta en los cinco.
Frontend `f98e431935838a4e3de45603f4a77d0e69be0225`: snapshot Git fijo,
`flutter analyze`, 243 pruebas y `flutter build web --release` pasaron
(`.local/p07-public-contact-frontend-final.log`). La primera ejecución falló en
cuatro pruebas nuevas que pulsaban Guardar antes de reconstruir el botón; se
corrigió la sincronización y se repitió la suite completa, sin relajar aserciones.
Los 15 casos focalizados incluyen es/en, 360/1200 px, conservación del borrador,
corrección/reintento y clasificación de errores sin filtrar diagnóstico privado.

`make test-workflows` pasó, incluido el caso nuevo de diagnóstico UTF-8
(`.local/p07-workflows-final.log`).
Las pruebas de handlers usan una BD nil para demostrar que el
rechazo se produce antes de intentar persistir. No sustituyen ensayos con roles
reales de PostgreSQL ni navegación integrada.

## Laboratorio integrado comprobado

`rac-browser-e2e-68710a812fda`, infra
`064cd446ca4c4407b3834d3ef907ef81d9d687a0` y ocho revisiones exactas del
manifiesto candidato: pasaron chat, reservas, onboarding, reseñas, notificaciones,
admin y agenda (`.local/p07-browser-all-final.log`, exit 0).
Onboarding comprobó con los servicios y PostgreSQL reales el rechazo de nombre,
biografía, intereses, descripción y notas con contacto; las lecturas posteriores
conservaron todos los datos guardados y el teléfono privado. La UI mostró el
aviso y permitió corregir/guardar. También pasó foto privada/pública y persistencia
tras recrear user-service. No se activó S3 ni respaldo externo para este ensayo.

Los ensayos previos descubrieron dos problemas del harness: Python hijo emitía
diagnósticos con la página de códigos de Windows mientras el padre esperaba
UTF-8; y Flutter agrupa el aviso en un nombre accesible con otros textos. Se
fijó el entorno UTF-8 con una prueba de subprocess y se exigió el mensaje completo
dentro del grupo, tras inspeccionar respuesta 400, árbol accesible y captura.
No se aceptaron respuestas incorrectas ni se relajó la persistencia esperada.

El laboratorio final y los dos anteriores se retiraron con su comando `stop`,
incluidos sus volúmenes propios. Se conservan fuentes y artefactos locales; el
almacenamiento RustFS de DEV no se modificó. Este ensayo no activa usuarios reales
ni cierra los pendientes de política o revisión jurídica.

## Pendientes de P07/P08

Contrato de reglas públicas/vectores de paridad para Flutter, corpus humano
independiente, configuración/versiones de política aprobadas y métricas sin PII.
Los resultados sintéticos del motor no se presentan como eficacia real.
P08 debe persistir revisiones y señales de contenido sospechoso y ofrecer una
cola humana; hasta entonces no se afirma que una palabra sospechosa retiene
automáticamente una publicación. Reseñas y chat se tratarán en P14 según su
superficie; no se amplía silenciosamente el análisis a comunicaciones privadas.
