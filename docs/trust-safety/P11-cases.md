# P11 — reportes, casos, acciones y apelaciones

Estado: **modelo unificado y consola staff de casos implementados y probados con
datos sintéticos; sin activar**. D02, D06, D07 y D10 siguen pendientes: no se
fijan SLA, plazo de apelación ni protecciones automáticas. Este estado no
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
- `appeals`: una por acción, solo del afectado y sin plazo hasta que se
  apruebe la política. La decide alguien que no participó en la acción; si se
  revoca la decisión, se registra una revocación.
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

## Pendiente

- Ingreso de reportes y apelaciones de clientes, con la autenticación del
  usuario y el snapshot aportado por el dueño de cada objetivo. Descripción
  cifrada mediante EvidenceStore.
- Consumidores de `ts.action.effective.v1` en user (standing), match y chat, y
  avisos versionados en alert (S13/S14) sin revelar al reportante.
- Consolas Flutter A1–A3/A5 y pantallas S12–S15.
- Inventario, backfill y retirada de `chat_reporte`, `chat_auditoria` y
  `reporte`, preservando los límites `hasta_version`/`hasta_numero_legacy`.
- Provisión DEV opt-in de los logins de casos e intake.
- Decisiones D06 (protección preventiva P0), D07 (SLA y plazo de apelación)
  y D10 (roles y autoridad legal).
