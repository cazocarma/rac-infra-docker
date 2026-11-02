# Trust & Safety — Fase 0

Estado al 2026-11-02: **P01–P03 con evidencia y cierre de P03; P04–P06 con
implementaciones y pendientes documentados; P07 en integración local**.
P05 y P06 tienen PRs en borrador con CI completa exitosa; eso no acredita su
activación ni cierra los pendientes humanos. Inspección inicial: 2026-10-22.

Este expediente aplica la Fase 0 solicitada en `RAC/rac-trust-safety-prompt.md`, SHA-256 `157fa4cf129d11df81dc1e71521363887dee186b792c7d51637f843941ffc017`. El prompt exige presentar el plan y detenerse antes de implementar.

- [Estado comprobado](current-state.md): código, infraestructura y límites de la inspección.
- [Amenazas A1–A15](threat-model.md): controles y pruebas previstas.
- [Plan y decisiones humanas](plan.md): secuencia de PR, migraciones, gates y alcance.
- [Decisiones aprobadas el 2 de noviembre de 2026](decisions-2026-11-02.md).
- [P07: analizador y contactos públicos](P07-content-signals.md).
- [P08: snapshots inmutables y revisión de publicaciones](P08-listings.md).
- [Matriz de aceptación](acceptance.md): módulos M1–M17, pantallas y aceptación global.
- [P01: implementación, pruebas y límites](P01-foundation.md).
- [P02: aislamiento de servicios, Keycloak y activación pendiente](P02-service-isolation.md).
- [P03: cierre y evidencia del enforcement transversal](P03-close.md).
- [P04: documentos y aceptaciones](P04-documents.md).
- [P05: identidad y mayoría de edad](P05-identity.md).
- [P06: catálogo cerrado](P06-catalog.md).
- ADR: [001 standing](ADR-001-standing.md), [002 publicaciones](ADR-002-listing-revisions.md), [003 casos](ADR-003-cases.md), [004 evidencia](ADR-004-evidence.md), [005 identidad](ADR-005-identity.md), [006 señales](ADR-006-content-signals.md), [007 auditoría](ADR-007-audit.md).
- [ADR-008: dependencias Go privadas y vendoring generado](ADR-008-private-go-dependencies.md).

Las ADR definen la dirección técnica aprobada; sus decisiones jurídicas, operativas y de proveedores siguen pendientes. La matriz global contiene criterios futuros, no resultados de ejecución; los ensayos realizados se distinguen en P01. El objetivo medible es reducir abuso y demostrar actuaciones trazables; ninguna tecnología garantiza ausencia de delitos ni sustituye evaluación jurídica. No se declara cumplimiento legal, certificación de identidad ni inmutabilidad ya logrados.

Se conserva la instrucción anterior del proyecto: integraciones externas preparadas, sin activar cobros, correo/push, proveedores de identidad ni copias fuera del PC. Su contratación y activación requieren una decisión explícita. P01 crea un repositorio local y ensaya migraciones en contenedores desechables; no cambia permisos de GitHub ni aplica migraciones al stack DEV.
