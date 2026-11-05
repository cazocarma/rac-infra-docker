# P09 — pruebas locales de previsualización privada

Recursos sintéticos desechables, sin leer `.env`, puertos del host o recursos DEV.
No hubo push, CI remoto ni activación de flags.

Fuentes: user `df33bcba6bff32e701c1c8e04e1a13ee3f059b29`, admin
`914c6aaa31932be531cc4445b67782b1247acc34`, frontend
`6a566a88dca1fc9c5f8b30183200de2c0d433039`. La regresión congelada multi-repo se
registra al terminar, sin inferir éxito a partir de pruebas parciales.

| Verificación | Registro relativo a raíz RAC | Resultado |
|---|---|---|
| V049 fresh/upgrade/repetición/checksums y escenarios user, con preview SQL/HTTP exigido | `.local/p09-private-preview-migrations-2026-11-05.log` | exit 0; ensayo del árbol anterior, consolidado en user c11c345 |
| V049 con Flyway no superusuario, reader function-only de cuatro funciones y negativas de corrector/aprobador/tablas | `.local/p09-preview-permissions-final-2026-11-05.log` | exit 0 |
| RustFS/SQL/OCR, cuatro identidades IAM, preview HTTP autenticado desde staging y contenedor worker real | `.local/p09-private-preview-rustfs-2026-11-05.log` | exit 0, user df33bcb limpio |
| Go admin: race y vet de listingproxy/http | ejecución Docker Go1.27.3, admin 914c6aa | exit 0 |
| Go user: race y vet de listingreview/photostore | ejecución Docker Go1.27.3, user df33bcb | exit 0; pruebas DB condicionadas no cuentan aquí |
| Render Compose sintético y gates Make, sin arrancar servicios | `python -m unittest discover -s scripts -p test_listing_review_compose.py` | 2 pruebas, exit 0 |
| Git archive frontend: formato, analyze, 278 pruebas y web release | `.local/p09-frontend-6a566a88dc.log` | exit 0 |
| Archivo específico de preview desde el mismo Git archive, seis casos con nombres visibles | `.local/p09-private-preview-widgets-2026-11-05.log` | exit 0 |

En el ensayo RustFS se exige PASS de
`TestReaderPostgresHTTP/private-photo-preview/rustfs-read-only`. El JWT staff
sintético se verifica contra JWKS de prueba; el LOGIN reader no tiene tablas.
La fuente usada en ese subtest es un JPEG sintético con metadatos SQL preparados:
prueba resolución/readback/auditoría, no que ese JPEG haya pasado OCR. La misma suite
incluye por separado el recorrido de upload/worker/OCR nativo, ambos sin promoción.
El IAM permite al preview solo GetObject `*.jpg` del staging separado y deniega
originales, otros sufijos, Put (clave nueva o existente), Delete, List, ACL, policy
y acceso anónimo. La imagen del worker de esta ejecución es
`sha256:f908f32426d7469c6858e874b86b3dab66bab5bdaa8b0290dda3cfead5492608`.

El proxy recibe respuestas de un owner HTTP sintético con su propia verificación
de audiencia; no reemplaza un E2E proxy→owner→RustFS→navegador. Se prueba transferencia
JPEG de más de 256 KiB, ruta fija, cuerpo vacío, sanitización de cookies/diagnósticos,
falta de cualquiera de las audiencias, rol insuficiente y rechazo de respuestas
sobredimensionadas/tipo erróneo. El owner verifica digest/tamaño exactos y audita
antes de cualquier entrega; un error de la segunda auditoría retiene la imagen.

No demuestra aprobación/promoción, retirada, restauración de referencias con datos
V048, navegación con Keycloak real ni gates finales de P08/P09/P15.
La build web conserva la advertencia previa de fuente CupertinoIcons; analyze no
reportó observaciones. Los textos nuevos conservan `legal_review: pending`.

La primera regresión integrada congelada está en
`.local/rac-p09-queue-proof-a071dedfa511/`: `revisions.json` fija infra
`46aee54f0e7ec98e43972f8dd67969ec5688f3b0` y los ocho companions. Permisos terminó
exit 0; migraciones terminó exit 1 por una indentación añadida al assert obligatorio
después de iniciar el ensayo preliminar. No se ejecutaron las otras tres etapas.
Se conserva el fallo; no se reporta la regresión como verde.

El script se corrigió y `make test-workflows` ahora comienza compilando en memoria
los fuentes Python de scripts/tools, sin ejecutar herramientas ni generar pyc.
Dos casos comprueban el error de indentación, ausencia de ejecución de top-level
y checkout vacío. La comprobación de 110 fuentes y el gate de workflows completo
pasaron, registro `.local/p09-python-preflight-workflows-2026-11-05.log`.
La siguiente regresión usa un nuevo snapshot; no se modifica el expediente fallido.
