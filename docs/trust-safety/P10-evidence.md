# P10 — almacenamiento de evidencias

Estado: **EvidenceStore implementado y probado con datos sintéticos; sin activar**.
No se activó almacenamiento de evidencias reales, política de retención ni hold
de usuarios. Las decisiones D08/D10/D11/D14 conservan sus gates.

## Gate técnico local — 2026-11-05

`make test-evidence-storage` crea una red, una instancia RustFS y un volumen
exclusivos con nombres aleatorios. Solo emplea credenciales y objetos sintéticos.
No lee `.env`, monta volúmenes existentes, publica puertos ni conecta con DEV.
El volumen se conserva durante un reinicio del proceso para probar persistencia;
todos los recursos propios se retiran al terminar.

Probado contra la imagen fijada en el laboratorio:
`rustfs/rustfs:1.0.3@sha256:9ca9559533b537d10482fe923288b676ad08f92a7069d9a17327fbae3cab688b`.
El ensayo terminó exit 0; registro local
`.local/p10-storage-capabilities-2026-11-05.log`.

Comprobaciones observadas:

- Versioning/Object Lock habilitados y VersionId no nulo.
- Retención COMPLIANCE sintética de cinco minutos: ni root puede borrar la
  versión, usar bypass GOVERNANCE, acortar la fecha o bajar el modo.
- Sobrescribir la clave crea otra versión; un delete marker no destruye la
  versión retenida. Las futuras referencias de evidencia deben incluir VersionId,
  no resolver solamente la clave más reciente.
- El intento de force-delete del bucket falla y la versión retenida sigue
  legible. Es una regresión del aviso oficial
  [GHSA-28w4-rp2p-636w](https://github.com/rustfs/rustfs/security/advisories/GHSA-28w4-rp2p-636w),
  que identifica 1.0.0 como afectada y 1.0.2 como corregida. No se probó contra
  instalaciones de otras personas ni contra buckets existentes.
- Legal Hold ON impide borrar la versión; el proveedor permite a root quitar
  el hold. La aplicación deberá restringir y auditar esa autoridad en P12.
- Bytes/digest y retención COMPLIANCE sobreviven al reinicio de RustFS con el
  mismo volumen exclusivo.

Este resultado acredita esos comportamientos de la API en esa imagen y fixture.
No certifica conformidad jurídica, resistencia a un administrador del host que
borra el volumen, respaldo externo, custodia de claves, configuración productiva,
IAM de evidencias ni cumplimiento de objetivos de recuperación.

## EvidenceStore — implementación local

- `rac-platform/evidence`: puerto sin SDK. Cada evidencia se sella con una
  clave de datos AES-256-GCM nueva; la clave se envuelve con un `KeyWrapper`
  externo al backup. El AAD vincula id, finalidad, caso, actor, procedencia,
  política, tipo, tamaño, digest, clave y retención: reetiquetar falla. Las
  finalidades y procedencias son cerradas (sin exportes completos de chat).
  `Capabilities.Require` exige versionado, Object Lock, COMPLIANCE, legal hold
  y lectura por versión exacta; si falta algo, rechaza capturar.
  `LocalKeyring` es solo DEV/pruebas, admite rotación y no es custodia (D14).
- `Commit` escribe una sola vez (`If-None-Match`), comprueba retención
  COMPLIANCE no menor a la solicitada y relee los bytes de la versión exacta.
  La retención se redondea hacia arriba al segundo para no acortarla.
- `rac-admin-service/internal/evidencestore`: adaptador S3 sin borrado,
  listado, ACL, presign ni modificación de retención, y servicio con logins
  separados de captura y lectura. Captura: intent → objeto verificado →
  versión ligada. Lectura: acceso y auditoría en la misma transacción,
  descifrado, nueva verificación de MFA y commit antes de entregar el contenido.
- `V054__evidence_manifests.sql`: esquema `ts` del dueño T&S, manifiestos
  append-only (un intent solo puede pasar una vez a `stored`), accesos y
  políticas de retención sin semilla. Sin política registrada no hay captura;
  la retención no puede superar el máximo de la política. Agrega la acción de
  auditoría `evidence.captured`. Sin grants: la provisión DEV de logins sigue
  pendiente y la verificación de asignación al caso llega con P11.
- Permisos staff: `evidence.capture` para ts_agent/ts_lead; `evidence.read`
  también para legal. Support y business_admin no reciben ninguno.

Pruebas locales:

- `.local/p10-evidence-store-rustfs-2026-11-05.log`, exit 0: RustFS y
  PostgreSQL desechables; bucket sin Object Lock rechazado, captura sellada,
  apertura por versión exacta, escritura única, borrado/acortamiento negados,
  aislamiento del delete marker, sin texto plano en el objeto, logins separados,
  permisos, justificación, MFA vencida durante la lectura y sin acceso directo
  al registro.
- `evidence_fixture.py` dentro de `test_database_permissions.py`: falla cerrado
  sin política, roles de cliente y lector no capturan, replays exactos,
  conflictos, clave/versión ajenas rechazadas, historia inmutable incluso para
  el propietario, conteos exactos de auditoría y política retirada.

## Entrega pendiente

- Autorización por asignación de caso y conflicto de interés (P11), provisión
  DEV opt-in de los logins y registro operativo de políticas aprobadas.
- Identidades separadas de retención, holds y export (P12); captura y lectura
  ya están separadas y auditadas.
- Claves fuera del backup de datos, rotación/custodia y prueba de restauración
  de ciphertext, manifiestos y claves con la separación aprobada.
- Retenciones por clase aprobadas, aplicación de holds y entrega a autoridades
  conforme a P12; no sembrar plazos reales por una prueba técnica.
- Configuración runtime opt-in y trazabilidad del release. El gate de
  capacidades ya rechaza un endpoint S3 sin COMPLIANCE verificado.
- Revalidar restart/backup/restore e IAM después de cualquier cambio de versión,
  topología o backend. La copia fuera del PC sigue aplazada.
