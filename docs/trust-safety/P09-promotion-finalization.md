# P09 — finalización atómica de medios aprobados

V051 y user `d0da15085e1f406f9a13a0cb14172238ff1cc846`. Backend interno probado
con PostgreSQL/RustFS, todavía sin endpoint, configuración runtime, provisión de
login o botón de consola para ejecutarlo. No se activaron flags ni se concedieron
permisos al migrar. P08/P09 no están cerrados.

Entrega posterior: [endpoint/opt-in V052](P09-photo-approval-ingress.md), con un
sexto permiso de readiness y proxy; la consola/activación sigue pendiente.

## Fronteras

El coordinador usa exclusivamente estas funciones de un LOGIN aislado: ready,
approval_context, prepare_photo_promotion, photo_promotion_result y
finalize_photo_promotion. No recibe tablas ni la función interna approve_core.
Los tres logins de P08 conservan sus permisos y rutas existentes; aún no se
extiende la herramienta de provisión para esta autoridad nueva.

La aprobación sin foto mantiene el mismo OID/firma/grants y delega al núcleo
común con una referencia de promoción nula. Sigue rechazando fotos; tampoco
reinterpreta el replay de una aprobación fotográfica como una aprobación ordinaria.
El núcleo compartido conserva revalidación de estado, standing/restricciones,
catálogo, política, autor distinto del dueño, versión/hash y evento idempotente.
Los requisitos de documentos/identidad usan el mismo helper de P08, con la
transacción del propietario abierta y sus locks vigentes hasta confirmar el writer.
Ninguna transacción se mantiene durante S3.

Antes de preparar/copiar, el coordinador consulta el resultado del evento exacto.
Un resultado confirmado devuelve el ACK original sin nuevos efectos o I/O S3.
Evento ajeno o parámetros incompatibles producen conflicto. Si aún no existe
decisión, prepara/accede/copia/readback y finaliza con el recibo privado en memoria.

La finalización verifica el recibo contra el intento, actor, LOGIN, políticas,
revisión/hash/versión, digest y tamaño. Comprueba el gate efectivo, fuente
disponible del pipeline y expiración del intento. El commit guarda juntos:

- VersionId exacto, digest/tamaño y referencia del intento de acceso.
- Decisión humana, evento de auditoría y outbox.
- Referencia inmutable de la revisión al medio.
- Puntero/estado/versión publicados del listing.

El receipt no puede confirmarse sin una decisión/referencia correspondiente. Un
constraint trigger diferido verifica además la pareja y los plazos al COMMIT,
con reloj de PostgreSQL. El deadline de autorización proviene de la sesión staff
verificada: mínimo de expiración y límite de antigüedad MFA. No es un plazo que
pueda elegir el cliente. La frontera Go también vuelve a comprobar la sesión.

Una copia cuyo commit falla queda privada, ligada al intento, sin DELETE
compensatorio. Un retry puede verificar esa misma versión; un ACK de aprobación
perdido se recupera por resultado y no vuelve a copiar. Una aprobación confirmada
no se repite ni reactiva si después cambia el estado de la cuenta.

## Pruebas locales y alcance

Datos sintéticos, recursos desechables, sin .env, puertos publicados o cambios DEV.

| Gate | Registro relativo a raíz RAC | Resultado |
|---|---|---|
| Flyway fresh V001–V051 + reader/intent/finalización SQL/HTTP de prueba | `.local/p09-finalization-sql-2026-11-05.log` | exit 0, ensayo preliminar del árbol luego consolidado en d0da150 |
| Race y vet listingreview | ejecución Docker Go1.27.3 sobre d0da150 | exit 0; DB condicionadas no cuentan aquí |
| SQL/S3/OCR/IAM/worker y finalización con proveedor real | `.local/p09-finalization-rustfs-2026-11-05.log` | exit 0, user d0da150 limpio |
| Migraciones completas/user fresh/upgrade/repetición/checksum y regresión P08 | `.local/p09-finalization-migrations-2026-11-05.log` | exit 0 |
| Flyway sin superusuario, ACL y backup/restore del laboratorio existente | `.local/p09-finalization-permissions-2026-11-05.log` | exit 0 |

Se exige PASS de `TestReaderPostgresHTTP/photo-finalization` y, en S3,
`TestReaderPostgresHTTP/photo-finalization/rustfs-complete-no-recopy`.
La sesión del coordinador es una Session staff sintética del test; la suite
conserva autenticación JWT/HTTP por separado. No se presenta como E2E Keycloak.
Las condiciones jurídicas se modelan con un prerequisite hook; no se declara
proveedor KYC o textos jurídicos aprobados. El JPEG/metadata de esta revisión es
una fixture preparada; el OCR nativo real se prueba por separado en la misma suite.

Casos: éxito/replay sin I/O, actor incompatible, negativa de tablas e historial
inmutable, cambio de requisitos/política/standing/catálogo durante la copia, fallo
tardío real del outbox (se verifica su error específico), MFA después del SQL,
deadline vencido durante una transacción que intenta commit y dos revisores
concurrentes con un solo ganador/recibo/outbox/puntero. La imagen del worker fue
`sha256:2fa2b4b292ae5494ccaf18759af3da33d274fd0418772953f612240c92c9040e`.

Pendiente: provisión/ready/configuración/ingress/proxy/consola y señales de imagen,
URLs autorizadas/retirada y corte público que retire los bypasses legacy. Restaurar
las nuevas tablas con datos y validar sus referencias/objetos también sigue
pendiente; un dump de laboratorio sin estos registros no demuestra esa restauración.
Este almacén no es EvidenceStore ni WORM, y un actor privilegiado conserva sus
facultades sobre infraestructura. P10–P15 siguen dentro del objetivo general.
