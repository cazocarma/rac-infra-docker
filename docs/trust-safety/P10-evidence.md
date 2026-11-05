# P10 — almacenamiento de evidencias

Estado: **iniciada la validación del proveedor; EvidenceStore no implementado**.
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

## Entrega pendiente

- EvidenceStore con snapshots acotados, cifrado autenticado y manifiestos
  versionados; casos/actores/finalidad autorizados por el dueño T&S.
- Identidades y permisos separados de captura, lectura, retención y export;
  acceso auditado antes de revelar contenido.
- Claves fuera del backup de datos, rotación/custodia y prueba de restauración
  de ciphertext, manifiestos y claves con la separación aprobada.
- Retenciones por clase aprobadas, aplicación de holds y entrega a autoridades
  conforme a P12; no sembrar plazos reales por una prueba técnica.
- Gate fail-closed de capacidades/configuración y trazabilidad del release.
  Aceptar un endpoint compatible con S3 no basta para habilitar evidencias.
- Revalidar restart/backup/restore e IAM después de cualquier cambio de versión,
  topología o backend. La copia fuera del PC sigue aplazada.
