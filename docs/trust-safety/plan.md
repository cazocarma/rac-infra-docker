# Plan de implementación — aprobado

Fecha: 2026-10-22. El usuario aprobó ejecutar este plan después de revisar la Fase 0. [P01](P01-foundation.md) y [P02](P02-service-isolation.md) registran implementaciones locales y sus ensayos, sin activación sobre DEV. La aprobación técnica no resuelve las decisiones jurídicas, operativas, de proveedores o activación indicadas abajo.

## Estrategia y dependencias

Primero cerrar identidad/autorización/auditoría; después impedir contenido público sin revisar; luego unificar actuación y derechos. Todo en DEV con datos sintéticos. QA verifica el mismo manifiesto de revisiones y artefactos promovidos; PRD permanece bloqueado sin responsables, textos, proveedores y validaciones. No contratar servicios ni habilitar cobros/correo/push/copia externa por inferencia de este plan.

Dirección aprobada: nuevo repositorio Go `rac-platform` con standing, audit, contentsignals, policy, retention. Contiene reglas/tipos y puertos comunes; ningún singleton global, credenciales o SQL de otro dueño. Adaptadores tecnológicos compartidos sin dueño de negocio pueden residir en subpaquetes, como audit/postgres. `rac-shared-contracts` mantiene contratos OpenAPI/JSON Schema, no se convierte incidentalmente en repositorio de toda la lógica. Versiones del módulo fijadas en go.mod; go.work solo para desarrollo. El repo local está creado; publicación remota e instalación de la App no se han realizado.

Admin será dueño de T&S con esquema propio; user de standing/KYC/publicaciones/reseñas; match de reservas/cupos; chat de mensajes; alert de entrega de avisos. No convertir infra en microservicio de negocio: allí quedan Compose, migraciones forward, políticas de despliegue, runbooks y documentación. La existencia de una BD física compartida no autoriza a saltarse APIs dueñas.

Se aprobó adelantar M14 mínimo antes de cualquier consola sensible y la base M12 antes de migrar reportes M10: el orden literal del prompt deja accesos y snapshots sin sus dependencias. El resto conserva su secuencia.

## Serie propuesta de PR

Cada fila es una unidad de entrega coordinada; puede necesitar PR enlazados en varios repos. No hay despliegue parcial que deje una ruta alternativa abierta. Un manifiesto fija SHA/imagen/digest y esquema de cada conjunto.

| PR lógico | Entrega y repos | Migración forward propuesta | Gate de salida |
|---|---|---|---|
| P01 | Módulo común, contratos de errores/eventos/política/audit; M15 base; infra, platform, dueños | Cabeceras/cadena, políticas y privilegios de auditoría | Canonicalización, append concurrente, permisos negativos, verify/tamper; ningún PII |
| P02 | M17 esencial y M14 mínimo: Keycloak fijado, DB roles por dueño, cliente técnico mínimo, MFA/step-up consola; gateway/auth | Grants DML por servicio y migrador separado | Asignar solo compa; intento admin/otro realm denegado; suspensión permite login; backup/restore permisos |
| P03 | M1 transversal; user y todos los escritores, RabbitMQ/alert/contracts/Flutter | Standing, restricciones, outbox/inbox/proyecciones | JWT viejo, versión obsoleta, partición, commit race, p99 y permisos por endpoint |
| P04 | M13: documentos inmutables/aceptaciones; i18n ARB + metadata, plantillas backend | Documentos, versiones, aceptaciones y flags de aprobación | 428 en acciones cubiertas; derechos/reportes/apelación nunca bloqueados; texto pending no publicado como definitivo |
| P05 | M2: puerto KYC/fake DEV; renombre email_verified en user/Flutter/contracts | Verificaciones, fingerprint/key_id; renombre y minimización aprobada | Firma/replay, minor/adult, fake fuera DEV falla; email no implica identidad |
| P06 | M3: catálogo y geografía; user/Flutter/contracts | Categorías/actividades; backfill controlado de skills | Desconocidas no publicadas; retirada API libre; filtros sin consultas sensibles en logs |
| P07 | M5: signals/policy/corpus y reglas públicas contacto | Léxico/umbrales versionados, sin listas privadas en app | Recall/FP baseline no vacía; fuzzing/CPU; sin ban automático |
| P08 | M4: revisión previa, onboarding y consola A4; user/admin/Flutter | Listings/revisiones/decisiones, backfill no publicado | Cambio de perfil/foto no evita revisión; carreras KYC/standing; rutas antiguas retiradas |
| P09 | M6: cuarentena/OCR/pHash y medios aprobados; user/worker/infra | Photo assets/versiones/resultados/referencias de revisión | OCR contacto, EXIF, IAM, URL breve, corpus transformaciones y falsos positivos |
| P10 | M12 base: EvidenceStore, cifrado, snapshot, política y prueba COMPLIANCE | Evidencias, manifiestos, acceso y retención | Gate de proveedor: no evidencia real sin capacidad demostrada; sin clave junto al backup |
| P11 | M10/M11: reportes/casos/acciones/apelaciones, avisos, S12–S15/A1–A3/A5; admin/chat/user/alert/Flutter | Backfill de chat; report/case/action/appeal; retirada final del modelo viejo | Límites legacy preservados, conteos, cuatro ojos, autocaso denegado, acceso auditado previo |
| P12 | M12 completo: derechos, holds, autoridad y restore; todos los dueños/infra | Sagas, holds/aprobaciones, tombstones, export manifests | Restore aislado reaplica supresión antes de tráfico; hold mínimo; export acotado; destino externo aún gateado |
| P13 | M7: reservas seguras/check-in, S8/S9/S11; match/user/admin/alert/Flutter | Actividad/lugar, aceptación seguridad, check-ins y señales de velocidad | 422 límites; DST/concurrencia; enforcement cancela/devuelve cupo; ayuda no simula emergencia |
| P14 | M8/M9: chat y reseñas; chat/user/admin/Flutter | Estados moderación reseña y eventos asociados | Advertencia cliente; servidor chat off; URLs sin preview; reporte y procedencia reseña |
| P15 | M14 completo/M16/M17 restante: consolas, métricas, headers/rate limits, CI hardening; infra y todos | Políticas/permisos finales y cleanup de grants | E2E-01–14, carga, Loki sin PII, restauración, seguridad independiente y operación humana |

Los números SQL reales se asignan al abrir cada PR tras revisar la rama base. La Fase 0 inspeccionó hasta V017; P01 agrega V018 y P02 agrega V019 sin reescribir V001–V017. Se ensayaron en contenedores desechables y no están aplicadas a la BD DEV. Los siguientes números no quedan reservados por esta tabla.

## Decisiones humanas

Salvo la dirección técnica D01 aprobada con este plan, siguen `DECISION_REQUIRED`. Recomendaciones no equivalen a aprobación. Decisiones de producto no pueden suplir las que requieren asesoría jurídica o presupuesto.

| ID | Decisión / propuesta segura | Bloquea |
|---|---|---|
| D01 | Dirección técnica aprobada: rac-platform y dueño T&S en admin. Repo local creado. Publicación remota e instalación de lectura de CI aún no realizadas; sin permisos de escritura de App | Publicación integrada |
| D02 | Matriz completa de capacidades: seguridad, cancelación, privacidad y recuperación además de siete iniciales; conservar login y derechos. Resolver banned fuera de plazo sin cerrar canales obligatorios | P03/P11 |
| D03 | Enforcement cancela futuras reservas y devuelve cupo a contraparte aunque cambie semana; reversión no resucita reserva ni cargo. Definir tratamiento del cupo del sancionado y de actividad ya iniciada | P03/P13 |
| D04 | Catálogo permitido, geografía Chile, máximo cinco y tipos de lugar. Precios mínimo/máximo CLP y percentiles sin inventar cifras | P06/P08/P13 |
| D05 | Adulto/KYC para publicar y primera reserva; proveedor, coste, cobertura chilena, liveness, DPA, error/recurso y borrado | Activación KYC/usuarios reales |
| D06 | Autoocultar por P0/P1 versus denuncias abusivas: proponer triaje y señales corroboradas; P0 permite restricción preventiva reversible. Definir excepcional suspensión P0 y revisión rápida, nunca ban automático | P11 y E2E-07 |
| D07 | Responsables y horario de atención; taxonomía, SLA 1/24/72/168 h y apelación 30 días propuestos. Sin equipo no prometer plazos | Operación de P11 |
| D08 | Base/finalidad, plazos por clase, derechos, holds, texto legal y vigencia normativa. Aprobar antes de retener de forma irreversible; no declarar cumplimiento de Ley 21.719 por tener módulos | P04/P10/P12 y usuarios reales |
| D09 | Rostro obligatorio: prompt pide guía con rostro pero flag false. Mantener false y texto coherente hasta decisión; moderación externa de imagen off | P09 |
| D10 | Roles staff, MFA/step-up, dos revisores disponibles, retención legal y export autoridad. Autoridad legal decide alcance, no business_admin | P02/P11/P12 |
| D11 | Destino externo, coste, gestión de claves/checkpoints y recuperación. Sigue aplazada la copia fuera del PC; diseño preparado sin activar | Anclaje independiente/restore completo/PRD |
| D12 | Fingerprint sin documento persistido y rotación de claves. Coincidencia de ban: revisión reversible frente a `rejected` del E2E-05; posible suplantación exige apelación | P05 y E2E-05 |
| D13 | Curación especializada de léxico y corpus. sexual_services/minors vacíos hasta revisión; no certificarlos por una suite vacía | P07/activación detectores |
| D14 | Política de auditoría: custodio de claves, destino anclaje, frecuencia, objetivos de recuperación y tolerancia a pérdida. Definir presupuesto de riesgo antes del gate | P01/P10/P15 |

Aprobar este plan permite desarrollar estructuras y fake DEV; no constituye aprobación jurídica, contratación ni autorización de activar los flags pendientes. Las decisiones no resueltas permiten avanzar módulos independientes, pero bloquean su activación correspondiente.

## Política versionada y pantallas

Cada política tiene versión inmutable, autor/aprobador, effective_at y motivo codificado. Parámetros del prompt (duración 60–480 min, anticipación 180 min, check-in +15 min, primera reunión pública, límites de velocidad, precio, umbrales, SLA, TTL/retención) se almacenan y evalúan del lado servidor. Se reconcilia el máximo actual 240 min antes de cambiar a 480 en UI/backend. Defaults sensibles se siembran como propuestas no activas; solo la versión aprobada se sirve al usuario. Un cliente viejo no puede escoger una política permisiva anterior.

S1–S3 acceso/documentos/KYC; S4–S7 onboarding/estado/explorar/perfil; S8–S9 reserva/detalle; S10 chat; S11 seguridad; S12–S15 reporte/aviso/restricción/apelación; S16 reseña; S17 privacidad. A1–A9 corresponden a casos, detalle, acción, revisión de publicación, apelaciones, legal, políticas, auditoría y métricas. Diseño mobile/web accesible con carga/error/vacío/reintento, estados reales y pruebas de autorización de navegación directa. Flujos aún no operativos muestran «En construcción» sin CTA que finja completar un trámite.

No incluir teléfonos de emergencia definitivos sin validar fuente oficial/jurisdicción al implementar. Ninguna pantalla promete vigilancia continua o rescate. ARB y plantillas llevan metadata legal_review; `LEGAL_PENDING` queda en configuración/metadata, no como jerga técnica en pantalla. Documentos incluyen hash del contenido servido y versión de aceptación, sin casillas premarcadas. El cuestionario no prueba jurídicamente consentimiento informado.

## Calidad, migración y despliegue

- Antes de cada cambio: base de PR y manifiesto coherentes, backup cifrado de DEV, inventario mínimo sin logs de datos y plan de reversa. No asumir ausencia de datos reales por el nombre DEV. Probar migración sobre copia aislada y redactada cuando proceda.
- Expandir/backfill/verificar/contraer dentro de una serie coordinada y ventana acotada. Ninguna ruta legacy queda como bypass permanente. Migraciones forward de compensación donde sea posible; cambios destructivos requieren restauración coordinada, no un down SQL que invente datos perdidos. Ningún rollback de servicio a esquema incompatible.
- Go: unitarias de dominio, `go test ./...`, race donde afecte concurrencia, integración testcontainers PostgreSQL/RabbitMQ/Keycloak y matriz de autorización por endpoint. Flutter: analyze, unit/widget y flujos de integración web/móvil. Pruebas deben comprobar límites/abuso, no repetir getters.
- CI de PR: contratos, migraciones limpias y upgrade desde V017, permisos, corpus, audit verify, escaneo de secretos/vulnerabilidades/código/imagen y SBOM del artefacto. Revisar lo que ya tenga cada repo antes de añadir herramientas duplicadas. Trivy/govulncheck u otras herramientas se seleccionan con versiones fijadas; no se afirma que ya estén todas configuradas.
- CI integrada usa tokens efímeros de App con lectura de repos explícitos y revisiones fijadas, sin secretos en PR no confiables. Construir una vez, promover el mismo digest, gates de entorno y aprobación humana para PRD. Nunca desplegar automáticamente a un servidor inexistente.
- Observabilidad: contadores de decisiones/cola/SLA/lag/reconciliación/denegación/retención, etiquetas enumeradas sin sujetos. Logs estructurados con allowlist; pruebas con canarios sintéticos en Loki, sin volcar contenido. Alarmas de pérdida de consumidor, evidencia pendiente, anclaje atrasado y fallo de supresión requieren responsable.
- M17 restante: secretos fuera de Git con proveedor aprobado, autenticación servicio-servicio de audience limitado o mTLS, rate limit IP/usuario no falsificable, anti-bot según decisión, CSP compatible con Flutter/PKCE, tokens web en memoria con transacción PKCE acotada para redirects. No romper el login ya corregido.
- Ensayar fallos de red, broker/DB, restore y rotación; documentar p99, muestra y carga. Pentest externo y revisión legal son gates pendientes, no tests simulados que puedan darse por hechos.

## Fases y criterio de salida

Fase A: P01–P15, decisiones aplicables resueltas y matriz de aceptación con evidencia; bloqueante para usuarios reales. No anunciar prevención total de ilícitos. Fase B antes de cobros: proveedor de pagos, impuestos, retracto/cancelación, suscripción, disputas y señales de contracargo, todo tras decisión y textos aprobados. Fase C: DPIA y revisión adicional antes de imágenes externas, chat en servidor o scoring avanzado. El chat privado seguirá fuera del análisis servidor por defecto.

P01 y P02 tienen evidencia local separada. La siguiente unidad es P03, estado de cuenta y enforcement transversal, previa matriz D02/D03; la activación local de P02 requiere el respaldo/recuperación indicado en su runbook. Mantener entregas revisables, sin mezclar toda la plataforma en un único PR.
