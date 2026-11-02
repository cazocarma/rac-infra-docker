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

Se preparó el tag local inmutable v0.15.0 en
`bb7522deed8ec129a761d34f23b2979afc048aa5`. El script existente
`scripts/vendor_platform.py v0.15.0` genera go.mod/go.sum/vendor de los cinco
consumidores desde ese tag, sin credenciales privadas dentro de Docker.
La publicación remota se registrará por separado; un tag local no prueba push.

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
Los resultados finales del frontend/navegador se añadirán al terminar sus
ejecuciones. Las pruebas de handlers usan una BD nil para demostrar que el
rechazo se produce antes de intentar persistir. No sustituyen ensayos con roles
reales de PostgreSQL ni navegación integrada.

## Pendientes de P07/P08

Contrato de reglas públicas/vectores de paridad para Flutter, corpus humano
independiente, configuración/versiones de política aprobadas y métricas sin PII.
Los resultados sintéticos del motor no se presentan como eficacia real.
P08 debe persistir revisiones y señales de contenido sospechoso y ofrecer una
cola humana; hasta entonces no se afirma que una palabra sospechosa retiene
automáticamente una publicación. Reseñas y chat se tratarán en P14 según su
superficie; no se amplía silenciosamente el análisis a comunicaciones privadas.
