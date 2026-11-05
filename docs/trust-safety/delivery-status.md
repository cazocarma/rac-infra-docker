# Seguimiento de entregas — 2026-11-05

Este archivo separa desarrollo, pruebas y activación. La aprobación del plan no
autoriza inventar decisiones jurídicas ni convertir un componente aislado en una
fase cerrada. Los gates originales siguen en [plan.md](plan.md) y
[acceptance.md](acceptance.md); las decisiones vigentes en
[decisions-2026-11-02.md](decisions-2026-11-02.md).

| Fase | Situación de trabajo | Siguiente comprobación o entrega |
|---|---|---|
| P01–P07 | Integradas según el cierre previo; documentos y ensayos por fase | Revalidar sus gates transversales al cerrar P15; proveedores y decisiones pendientes no se consideran resueltos |
| P08 | Revisión de snapshots, envío del compa y consola de aprobación integrados en main (infra #15) | Fotos aprobadas, lectura pública del snapshot aprobado, retirada de bypasses y matriz de navegador/autorización; motivos negativos pendientes de catálogo revisado |
| P09 | Fuentes privadas, OCR/pHash, cola/worker y subida recuperable; previsualización privada/proxy/consola; finalización atómica y endpoint/runtime opt-in probados con RustFS real; base Flutter de recuperación durable | Conectar recuperación y aprobación en consola, señales de imagen, retirada/URLs autorizadas; reconciliación, observabilidad, restore con datos y E2E |
| P10 | Gate local de capacidades RustFS probado: COMPLIANCE, versiones, hold, force-delete y persistencia tras reinicio; [evidencia](P10-evidence.md) | EvidenceStore, claves/cifrado, snapshots, IAM y gate de activación; prueba del proveedor no equivale a fase cerrada |
| P11 | Pendiente de integración del modelo unificado | Reportes/casos/acciones/apelaciones, conflictos de interés, avisos y retirada del modelo anterior |
| P12 | Pendiente | Derechos, retenciones/holds aprobados, sagas, export y restauración con supresiones antes de tráfico |
| P13 | Pendiente del plan T&S; reservas funcionales anteriores no cierran esta fase | Política temporal/geográfica, aceptación de seguridad, check-in y escenarios de protección |
| P14 | Pendiente del plan T&S; chat/reseñas anteriores no cierran esta fase | Avisos, estados de reseña, procedencia y reporte; análisis servidor de chat privado sigue desactivado |
| P15 | Pendiente | Consolas finales, métricas/logs sin PII, pruebas E2E/carga/restore y gates de operación |

Orden inmediato: cola real y permisos de P09 → ciclo de vida completo de medios
→ cierre del corte público P08 → EvidenceStore P10 → P11/P12 → P13/P14 → auditoría
de aceptación P15. Se mantienen pruebas locales antes de CI remoto. Las entregas
de varios repos deben conservar SHA coherentes en el manifiesto de infra.

No hay activación productiva implícita. KYC real, categorías/precios/comisión,
criterios operativos pendientes, textos/plazos jurídicos, foto obligatoria,
corpus especializado, copia externa y operaciones de dos personas conservan sus
gates. Se puede completar su estructura y prueba sintética sin afirmar que sus
dependencias humanas están aprobadas.
