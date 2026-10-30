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

Pendiente en P05: gates `IDENTITY_VERIFICATION_REQUIRED` al publicar y antes de la
primera reserva (match por autoridad, como documentos/standing), pantalla S3,
contrato OpenAPI, caso P1 por huella baneada (modelo de casos en P11) y
`DeleteSubjectData` dentro de la saga de supresión (P12).
