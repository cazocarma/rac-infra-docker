# P05 — Identidad y mayoría de edad (en desarrollo)

Sigue [ADR-005](ADR-005-identity.md). Rama `feat/identity-verification` en user e
infra, apilada sobre P04 (`feat/versioned-documents`). El proveedor real, el
tratamiento y la política siguen pendientes de D05/D08/D12. Nada de este
incremento activa obligaciones sobre usuarios: no hay gates todavía.

## Incremento 1: datos, puerto, fake DEV y renombre

V039 renombra `usuario.verificado` a `email_verified` en un corte coordinado,
sin alias. La columna solo reflejaba el claim OIDC `email_verified`. User escribe
el nombre nuevo, igual que el fixture `configure_identity.py`. `db/initdb` no se
monta en ningún Compose: es legado anterior a las migraciones y no se modifica.
Si se ejecutara antes de V001, el renombre lo corregiría. OpenAPI y Flutter no
usaban el campo.

`identity_verifications` guarda proveedor, referencia opaca, propósito, estado,
mayoría de edad, país y huella con `key_id`. No guarda imagen, número de
documento ni fecha de nacimiento. Las restricciones de la tabla exigen:

- una aprobación implica adulto con país y huella;
- huella y `key_id` van juntos;
- solo un estado `pending` registra fecha de decisión nula;
- un único intento pendiente por persona y propósito;
- referencia de proveedor única.

`banned_identity_fingerprints` y `identity_webhook_events` (solo identificadores
de evento, para replay) completan el modelo. `rac_user` puede insertar y
actualizar las columnas de resultado. No puede borrar, reescribir
`provider_ref`/`user_id`, leer eventos de webhook ni banear huellas: esto último
corresponde al dueño de T&S tras un caso.

User define el puerto `identity.Provider` (CreateSession, VerifyWebhook,
DeleteSubjectData). La huella es HMAC-SHA256 con separación de dominio sobre país
y el identificador estable **opaco** que entrega el proveedor, nunca sobre un
número de documento, que RAC no recibe. La rotación de clave sigue pendiente de
D12. Reglas:

| Resultado del proveedor | Estado en RAC |
|---|---|
| Menor de edad | `rejected`, sin huella |
| Edad indeterminada | `needs_review`, sin huella |
| Huella baneada | `needs_review` |
| Huella aprobada en otra cuenta | `needs_review` |
| Error o timeout | Queda `pending`, nunca aprobado |

Ninguna coincidencia banea automáticamente a una persona nueva (D12 pendiente).
Las aprobaciones concurrentes de una misma identidad se serializan con un lock
transaccional por huella. Un replay de `event_id` no tiene efecto y un resultado
distinto para un intento decidido es conflicto. Un intento nuevo sustituye al
pendiente. El correo verificado nunca equivale a identidad.

El adaptador `fake` solo se construye con `RAC_ENV` `dev` o `test`. El arranque
falla con otro ambiente, con un secreto de menos de 32 bytes o sin URL. Firma
`t=<unix>,v1=<hmac>` sobre los bytes originales, con ventana de 5 minutos, JSON
estricto y cuerpo acotado. Sus registros conservan `provider='fake'` y nunca
respaldan una insignia pública real. Sin `IDENTITY_PROVIDER` los endpoints
responden 503.

| Ruta | Acceso | Respuesta |
|---|---|---|
| `GET /api/user/me/identity` | Bearer | Solo el estado |
| `POST /api/user/me/identity/sessions` | Bearer | `{purpose}` → estado y URL |
| `POST /api/user/identity/webhook` | Firma del proveedor | Sin datos de estado; no sirve de oráculo |

Pruebas: unitarias de reglas, validación y huella (clave, país y separador); el
fake rechaza ambientes no DEV, firma ausente o ajena, cuerpo alterado, timestamp
viejo o futuro, campos desconocidos, JSON adicional y tamaño excesivo; HTTP
devuelve 503 sin proveedor y 401 sin token, y antes de almacenar rechaza un
propósito desconocido, un `user_id` elegido por el cliente y claves duplicadas.
`TestIdentityVerificationPostgres` corre con el rol real `rac_user` sobre el
esquema migrado: correo verificado sin identidad, sustitución, aprobación,
replay, conflicto, sesión desconocida, menor, edad indeterminada, duplicado,
huella baneada, carrera concurrente con exactamente una aprobación, ausencia de
la clave de identidad en el volcado y permisos negativos. `test_migrations.py`
comprueba además el renombre sin alias y que las restricciones rechazan ocho
filas inválidas, un segundo pendiente y una referencia reutilizada.

El primer ensayo PostgreSQL falló con el rechazo de un menor: el driver envía un
`[]byte` nulo como `bytea` vacío y la restricción de 32 bytes lo rechazaba. La
huella ausente ahora se envía como `NULL`. El reensayo pasó con salida 0,
incluidas todas las suites existentes de user sobre el esquema con V039:
`.local/p05-identity-migrations.log`.

## Incremento 2: gates, autoridad compartida y S3

`rac-platform` v0.14.0 agrega `identity`. Query y Observation se ligan a la
cuenta (subject Keycloak) y al propósito. `Check` falla cerrado: una lectura
ausente, lenta, vieja o de otra cuenta queda como no disponible, y solo pasa
una aprobación. El paquete incluye cliente HTTP autenticado, handler interno y
la respuesta pública 428 `IDENTITY_VERIFICATION_REQUIRED`, que solo lleva
`purpose` y `flow`; nunca detalle de la verificación. Los cinco consumidores
se generan con `vendor_platform.py`. El tag existe solo localmente hasta
publicar: `v0.13.0` no se toca.

**user:**

- Implementa la fuente (si hay una aprobación para el subject) y monta
  `/internal/identity` en el listener de autoridad.
- El lector tiene audiencia propia `rac-identity` y rol `identity.read`, ligado
  solo a `rac-match-standing`. Los tokens de standing o documentos, chat y alert
  reciben 401.
- `PUT /me/compa`, `POST /compas` y `POST /compas/:id/skills` exigen identidad
  aprobada con `IDENTITY_ENFORCEMENT_ENABLED=true`, después de documentos. El
  correo verificado y el rol compa no la sustituyen.
- Activar enforcement sin proveedor, o el fake fuera de dev/test, impide
  arrancar.

**match:**

- Exige identidad aprobada al crear una reserva, con el subject tomado de la
  propiedad almacenada y no de la solicitud.
- `require_kyc_client_before_booking` (`IDENTITY_CLIENT_BOOKING_REQUIRED`) queda
  activo por defecto al habilitar identidad. Es `DECISION_REQUIRED`, así que
  solo un `false` explícito lo apaga.
- Cancelar, leer reservas y aceptar no dependen de identidad.
- Las aprobaciones todavía no se revocan, así que comprobar antes de la
  transacción no compite con un retiro. Cuando P11 permita revocar, este punto
  debe pasar a comprobación dentro de la transacción.

`identity_standing.py` provisiona la audiencia solo si `identity=True` y solo
para match. El enforcement queda apagado en todos los Compose hasta que D05
apruebe un proveedor real.

Frontend 834925b agrega S3 en `/identity`: por qué se pide, qué se guarda,
proveedor externo, duración y que no constituye antecedentes. Muestra los
estados none/pending/approved/rejected/needs_review/expired y abre la URL del
proveedor fuera de la app. Con 503 (sin proveedor) informa que no está
disponible, sin CTA que simule el trámite. Reserva y publicación compa
reconocen el 428 de identidad y ofrecen verificar con el propósito
correspondiente. El mismo código con otro estado HTTP no cuenta. Son 22
claves ARB pending. El contrato OpenAPI documenta las tres rutas, el esquema
`IdentityVerificationRequired` y el 428 de reserva y publicación.

Pruebas y hallazgos:

- Plataforma: race completo; Check y transporte con cuenta ajena, timestamp
  viejo o futuro, campos extra, sin autenticación y ruta 503.
- user: gate apagado y encendido en las tres rutas, consulta ligada al subject,
  503 sin proveedor, aislamiento del listener por token y cliente, y
  configuración inválida.
- match: configuración y caso PostgreSQL real dentro de
  `TestBookingDocumentsPostgres`. Una reserva sin identidad recibe 428 y no
  crea fila; aprobada, sigue el flujo existente.
- Keycloak real: idempotente; solo match recibe `rac-identity`; desactivarlo
  la retira.
- Frontend: 232 pruebas, análisis y build.
- Hallazgos de las pruebas reales: el servicio de match traducía cualquier
  error no previsto a `booking_unavailable`, ocultando el 428; ahora deja pasar
  los errores de identidad. La prueba de Keycloak sobrescribía un secreto en
  un bucle.

Laboratorio `rac-browser-e2e-0d4120e240fe` con los pins P05 (V039, platform
v0.14.0, gates apagados por defecto): pasaron las siete suites reales (chat,
reservas, onboarding, reseñas, inbox, administración y agenda) y se retiró sin
recursos. El renombre `email_verified` no rompe login, perfil ni onboarding. La
migración y las suites PostgreSQL de user, match y chat pasaron
(`.local/p05-gates-migrations*.log`), al igual que el test real de Keycloak.
Un primer intento cayó por falta de memoria del daemon Docker durante otra
compilación y no por el código; se repitió aislado. Platform v0.14.0 y las
ramas de los compañeros se publicaron antes de infra.

Pendiente en P05: caso P1 por huella baneada (modelo de casos en P11),
`DeleteSubjectData` dentro de la saga de supresión (P12), estrategia de rotación
de la huella (D12), proveedor real y su contrato (D05), insignia pública solo
derivada de proveedores reales (P08/S7) y Compose de rollout cuando haya
proveedor aprobado.
