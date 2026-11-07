# P11 — reportes, casos, acciones y apelaciones

Estado: **modelo unificado y consola staff de casos implementados y probados con
datos sintéticos; sin activar**. D02, D06, D07 y D10 tienen dirección aprobada
([registro](decisions-2026-11-02.md)): apelación dentro de 30 días, sin SLA de
respuesta, sin sanción automática y operaciones de dos personas bloqueadas con un
solo operador. Faltan criterios corroborables de urgencia y horario/suplencia. Este estado no
cierra la fase.

## Implementado

`V055__trust_safety_cases.sql` (esquema `ts`, dueño T&S en admin):

- `reports`: objetivo tipado (cuenta, revisión, foto, reseña, conversación,
  reserva), sujeto aportado por el dueño del objetivo y categoría con
  severidad P0–P3. Un índice parcial permite un solo reporte abierto por
  reportante y objetivo, incluidos los reintentos concurrentes. Nadie puede
  reportarse a sí mismo. El reportante solo recibe el acuse, nunca el caso.
- `cases`: se agrupan por sujeto y severidad. `case_events` es append-only.
- `case_assignments`: hay una asignación activa por caso. Ni el sujeto ni un
  reportante pueden asignar ni ser asignados (conflicto de interés).
- `case_queue` y `case_detail`: la cola no expone sujeto ni contenido; el
  detalle es solo para quien tiene el caso asignado y no revela la identidad
  del reportante. Cada lectura se audita.
- `actions`: una advertencia o restricción asignada es efectiva al proponerse.
  Ban y suspensión quedan propuestos hasta que los aprueba otra persona; los
  CHECK lo imponen incluso al propietario del esquema. Revocar crea una acción
  vinculada y nunca reescribe la historia. Los comandos se repiten por id de
  evento sin duplicar efectos.
- `appeals`: una por acción y solo del afectado, presentada dentro de los
  treinta días siguientes a que la acción quedó efectiva (V060,
  `ts.appeal_window()`, D07). Fuera de plazo responde `appeal_window_closed`
  (55000). La respuesta incluye el plazo (`deadline`, UTC) y la repetición de
  una apelación presentada a tiempo sigue siendo idempotente después del plazo.
  Es un plazo para presentar, no un compromiso de tiempo de respuesta. La
  decide alguien que no participó en la acción; si se revoca la decisión, se
  registra una revocación.
- `outbox` emite `ts.action.effective.v1` para los dueños de cada efecto; este
  esquema no escribe standing, publicaciones, reservas ni chat.
- `evidence_open` exige ahora una asignación activa y sin conflicto
  (AccessGuard de P10).
- Nuevas acciones de auditoría: `report.received`, `case.assigned`,
  `action.decided` y `appeal.decided`.

`rac-admin-service/internal/cases` se activa solo con `TS_CASES_ENABLED=true`.
Usa un login que únicamente puede ejecutar funciones, cuerpos cerrados con id
de evento del cliente y comprueba los permisos staff y la vigencia de MFA antes
y después del commit. Los rechazos de la base de datos se traducen a códigos
estables. Rutas bajo `/api/admin/staff/cases`, `/actions/:id/...` y
`/appeals/:id/decision`.

`rac-platform v0.18.0`: `cases.read` y `cases.act` para ts_agent y ts_lead;
`cases.assign`, `cases.approve` y `appeals.decide` solo para ts_lead.

## Pruebas locales

- `case_fixture.py` dentro de `test_database_permissions.py` cubre:
  deduplicación, agrupación, autorreporte, categoría desconocida, conflictos,
  detalle sin el reportante, cuatro ojos, reintentos y eventos reutilizados,
  apelación independiente, revocación append-only, salida ordenada por outbox,
  conteo exacto de auditoría y denegación a otros servicios.
  Registro: `.local/p11-case-permissions-2026-11-05.log`, exit 0.
- `TestCasesPostgres` en el laboratorio `test_evidence_store.py`: HTTP staff
  sobre PostgreSQL real con los logins de staff e intake.
  Registro: `.local/p11-cases-http-2026-11-05.log`, exit 0.

## Recepción de efectos en standing

V056 define el ledger del dueño user: aplica restricciones, suspensión y ban por
la única ruta `standing.change_account`, conserva accesos protectores, revoca sin
reescribir acciones y permite recalcular vencimientos. Sigue sin existir un
consumidor de RabbitMQ ni una provisión activada de este ingreso.

V057 incorpora el comando JSON completo e inmutable por acción y el vínculo
inmutable de cada ID de entrega aceptado, incluidos los IDs alternativos para
una acción idéntica. Un duplicado con distinto caso, política, duración, inicio,
revocación, motivo o aviso se rechaza; un evento usado por otra acción no puede
retargetearse. Restricción, recibo y vínculo se confirman en la misma transacción.
La entrega concurrente de un evento para dos acciones solo puede tener un ganador.
Los roles de negocio no reciben lectura directa de estos registros.

La actualización desde V056 solo incorpora el comando original cuando el evento
del outbox de T&S coincide con el evento recibido y todos los campos conservados
en el ledger. Se marca `source_outbox_backfill`: no se presenta como un cuerpo
capturado originalmente por el receptor. Las recepciones nuevas usan `received`.
Una fuente ausente o contradictoria aborta la migración completa con
`ts_effect_receipt_reconciliation_required`, preservando el ledger anterior.
Debe investigarse la procedencia original antes de reintentar; no se permite
inventar el cuerpo perdido, cambiar IDs, desactivar triggers ni aceptar un
duplicado ambiguo para superar ese gate.

El relay, el consumidor y sus credenciales opt-in siguen pendientes. Estas
garantías de BD no equivalen a un transporte integrado ni a P11 cerrado.

V059 y `internal/tsrelay` añaden el [núcleo de publicación](P11-effect-relay.md):
funciones mínimas, confirmaciones ligadas a la transacción, reintentos con el
mismo evento y orden por principal desde el emisor. Se prueba con publisher
falso; faltan adapter AMQP, worker, topología/credenciales y consumidor reales.

### Identidad de la recepción — V058

El sujeto del comando nuevo es el `sub` UUID del realm RAC de Keycloak, igual que
los actores staff y reportantes de T&S. User lo resuelve exclusivamente por
`usuario.keycloak_id` bajo bloqueo de la relación; el ledger y el evento de
standing derivado siguen usando `usuario.id`. No hay búsqueda alternativa por
ID interno. El caso de colisión intencional entre el ID interno de A y el
principal de B debe resolver B, sin modificar el standing de A.

Los recibos anteriores reciben `subject_namespace=user_id` sin reescribir su
cuerpo ni el ledger. Un reintento histórico exacto reconoce solo la acción ya
aplicada, incluso si cambió la vinculación actual de Keycloak; nunca crea una
acción nueva mediante esa interpretación histórica. Los recibos nuevos usan
`keycloak_sub`. `subject_namespace` describe la identidad y `origin` distingue
recepción de reconstrucción: son propiedades diferentes e inmutables.

El contrato preparado está en `rac-shared-contracts`, commit
`f0b3c26a7339b38039cbcf880eeca8e32849d2bf`, archivo
`events/ts.action.effective.v1.schema.json`. El cuerpo cerrado no permite elegir
namespace ni aportar tokens o identidad del reportante. Sus límites de forma
coinciden con los campos del productor; no aprueban plazos de sanción ni criterios
jurídicos. La identidad del sujeto debe venir del snapshot del dueño del objetivo
en el intake pendiente, nunca de un campo libre del cliente.

`make test-standing-effects` ejecuta una prueba SQL focalizada sin copiar ni
compilar servicios Go: migraciones, IDs distintos/colisionados, reintentos,
revocación y actualización poblada. No sustituye la prueba general de permisos
con migrador no superusuario, dump/restore ni la integración con el broker.

### Validación local — 6 de noviembre de 2026

Referencia previa a V057: ensayos completos de migraciones (user/match/chat),
permisos y EvidenceStore/casos HTTP terminaron exit 0, en contenedores
descartables. Registros relativos a raíz RAC:
`.local/p11-verified-migrations-retry-2026-11-06.log`,
`.local/p11-verified-permissions-retry-2026-11-06.log` y
`.local/p11-verified-evidence-retry-2026-11-06.log`.
Los intentos iniciales sin `-retry` fallaron antes del ensayo porque el motor
Docker estaba apagado; se conservaron y no cuentan como pruebas de código.

V057 se probó desde Git limpio, infra
`f5d963db3f33fa1983fcf9544efe6852ddd927a1`, con los compañeros exactos indicados
en `.local/rac-p11-receipt-proof-b726c5bf7c7e/revisions.json`.
`results.json` registra exit 0 para sintaxis (116 fuentes Python), permisos y
migraciones con regresión user. Los dos snapshots anteriores `482444d0d02f` y
`67e2527187f7` también terminaron en verde, pero son iteraciones previas y no
sustituyen al snapshot final.

Cobertura de la versión final:

- Fresh y upgrade V018 con Flyway no superusuario, permisos negativos y roles
  de ingreso limitados a funciones.
- Todos los campos alterados del comando, IDs de evento cruzados y alternativos,
  colisión concurrente con un ganador, revocación y vencimiento.
- Recibos y vínculos inmutables; comando demasiado grande revierte sin efecto.
- Dump/restore conserva siete recibos y ocho vínculos de entrega sintéticos.
- Upgrade V056 poblado: importa el comando correlacionado y marca su procedencia;
  ausencia o contradicción aborta atómicamente sin perder el ledger anterior.
- Repetición de migraciones, checksums y regresión user/P08/P09/documentos.

No se aplicaron migraciones al DEV habitual ni se ejecutó CI remoto. Las pruebas
no demuestran todavía un flujo completo Keycloak→caso→broker→standing.

### Validación de identidad V058 — 6 de noviembre de 2026

Infra `8654ef0b0d7f242e85bf1515ee17893b539aee19` se exportó desde Git limpio,
con los compañeros fijados en
`.local/rac-p11-receipt-proof-6e75bc35cfe5/revisions.json`.
`results.json` confirma exit 0 en sintaxis (117 fuentes), permisos y migraciones
con regresión user. La suite de permisos incluye fresh/upgrade V018 con migrador
no superusuario y dump/restore de nueve recibos y diez vínculos sintéticos.

Los laboratorios focalizados también terminaron exit 0:
`.local/p11-principal-focused-2026-11-06.log` y
`.local/p11-principal-focused-final-2026-11-06.log`. Cubren IDs internos y de
Keycloak distintos, colisión entre namespaces de dos cuentas, principal ausente,
revocación cruzada, tipos/límites de comandos nuevos, helpers privados, replays
y una sola entrega ganadora bajo concurrencia. El upgrade poblado prueba que un
recibo histórico sigue reconociéndose después de cambiar la vinculación actual,
sin reinterpretar su identidad, y que una acción nueva solo resuelve el principal.

Contratos `f0b3c26a7339b38039cbcf880eeca8e32849d2bf`: 21 tests y validación
OpenAPI exit 0; registros `.local/p11-contract-principals-retry-2026-11-06.log`
y `.local/p11-contract-openapi-2026-11-06.log`. La ejecución inicial quedó
incompleta por faltar PyYAML en el venv; se instalaron las dependencias fijadas
por el CI existente en un venv local separado y se repitió la suite completa.
El esquema preparado no se consumió por AMQP ni se publicó remotamente.

Antes de activar el futuro consumidor debe comprobarse V058 como esquema mínimo:
la firma SQL por sí sola también existe en versiones que interpretaban otro
namespace. El intake y el recorrido real con tokens/owner snapshots/broker
siguen siendo gates abiertos; estas pruebas no los sustituyen.

## Ocultar una publicación (`hide_listing`) — V061

- La consola staff solo propone `hide_listing` con `target_id`, mediante
  `ts.listing_hide_propose`. El objetivo debe ser un `listing_revision`
  reportado en el mismo caso: si no lo es, responde `action_target_not_reported`
  (422). `action_propose` ya no acepta `hide_listing` sin objetivo. No lleva
  duración: dura hasta su revocación o hasta una apelación acogida, porque los
  criterios de vencimiento preventivo de D06 siguen abiertos.
- `ts.actions` guarda `target_type`/`target_id`; la revocación repite el
  objetivo. El cuerpo `ts.action.effective.v1` agrega `target` solo en esos
  casos, así que los demás tipos quedan idénticos byte a byte (contrato en
  rac-shared-contracts).
- User (`standing.apply_ts_effect`) comprueba que la revisión pertenezca al
  sujeto (`ts_effect_listing_mismatch`; si no existe, `ts_effect_listing_missing`).
  Registra una retención en `standing.listing_holds` y deja la publicación en
  `suspended`, el estado de cumplimiento que la aprobación ya rechaza. Cada
  revocación libera solo la retención con el mismo objetivo. Con la última
  liberada, la publicación vuelve a `published` con su snapshot aprobado, o a
  `unpublished` si no lo tenía.
- La lectura pública sigue en el perfil legado hasta el corte de P08: allí debe
  excluirse `suspended`. El dueño ve el estado en su consola. El aviso al dueño
  (S13) sigue pendiente.
- Pruebas: `case_fixture` (objetivo reportado, asignación, forma de la salida),
  `listing_hold_fixture` (propiedad, reintentos, retenciones apiladas,
  liberación con objetivo exacto, historia inmutable) y la prueba HTTP de admin
  en el laboratorio de evidencias.

## Pendiente

- Ingreso de reportes y apelaciones de clientes, con la autenticación del
  usuario y el snapshot aportado por el dueño de cada objetivo. Descripción
  cifrada mediante EvidenceStore.
- Consumidores de `ts.action.effective.v1` en user (standing), match y chat, y
  avisos versionados en alert (S13/S14) sin revelar al reportante.
- En el intake, obtener el principal canónico desde el snapshot autorizado del
  dueño del objetivo y verificar el recorrido completo desde el token del
  reportante hasta la recepción V058. La resolución del receptor y el contrato
  están implementados; el flujo público completo aún no lo está.
- Consolas Flutter A1–A3/A5 y pantallas S12–S15.
- Inventario, backfill y retirada de `chat_reporte`, `chat_auditoria` y
  `reporte`, preservando los límites `hasta_version`/`hasta_numero_legacy`.
- Provisión DEV opt-in del login de intake (los de casos, relay y consumidor ya
  están: `make ts-db-config`).
- Concretar los criterios preventivos D06, la cobertura de atención D07 y los
  procedimientos especializados D10. Las direcciones de producto ya fueron
  respondidas: operador inicial Cris A, treinta días para presentar apelación
  (no SLA), roles/MFA y decisiones humanas. Véase el
  [registro aprobado](decisions-2026-11-02.md); no repetir el cuestionario ni
  confundir aprobación de producto con una política jurídica activada.
