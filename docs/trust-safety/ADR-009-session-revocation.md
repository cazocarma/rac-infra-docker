# ADR-009 — Revocación acotada de sesiones

Estado: adaptador de identidad verificado localmente; orquestación durable y
activación pendientes. No declara cerrado P03.

## Problema

El [código de Keycloak 26.8.1](https://github.com/keycloak/keycloak/blob/26.8.1/services/src/main/java/org/keycloak/services/resources/admin/UserResource.java)
protege logout de usuario con el mismo `requireManage(user)` que modificación y
borrado. Conceder `manage-users` al provisionador de compa o a los lectores de
standing ampliaría su autoridad. Un proxy que conserve esa credencial tampoco
la convierte en un permiso IAM exclusivo de logout.

Repetir un logout global después de perder el ACK puede cerrar una sesión nueva,
creada para seguridad o apelación. Comparar fechas entre PostgreSQL y Keycloak
introduce una dependencia de relojes y de la resolución de los timestamps. Un
evento viejo posterior a una reversión tampoco debe cerrar la nueva sesión.

## Decisión técnica

Usar el SPI de [endpoints REST de Keycloak](https://www.keycloak.org/docs/latest/server_development/index.html#_extensions_rest)
para dos operaciones sobre sesiones. El adaptador reside en
`keycloak/session-control`, junto a los otros adaptadores de identidad de infra;
las reglas de sanción y su orquestación siguen perteneciendo a user.

No añade tablas JPA, modifica atributos de usuario ni guarda motivos de casos en
Keycloak. Usa los proveedores de sesiones del servidor, con peticiones síncronas
y su ciclo de transacción. La imagen y dependencias se fijan a 26.8.1; el SPI es
interno y exige volver a ejecutar la prueba real ante un upgrade. No se presenta
como un contrato binario estable entre versiones de Keycloak.

La extensión viene inactiva. Requiere la propiedad de proveedor
`--spi-realm-restapi-extension--rac-sessions--active=true`, en el realm fijo
`rentacompa`. Requiere además token firmado válido con audience
`rac-session-control`, cliente emisor `rac-standing-sessions`, rol de recurso
`sessions.revoke` y sujeto realmente vinculado a la service account de ese cliente.
Una persona con el mismo rol no adquiere ese acceso. No acepta una cookie de SSO
como autorización. El cliente no tiene `realm-management`, flujo de contraseña,
redirects ni sesión interactiva. Sus tokens duran como máximo 60 segundos.

### Contrato mínimo

- `GET /realms/rentacompa/rac-sessions/users/{keycloak_id}/sessions`: devuelve
  únicamente `complete` y una lista de `{id, offline}`. No expone IP, agente,
  nombres, correos, credenciales ni contenido. Máximo 4096 referencias; el exceso
  devuelve 409 sin truncar ni fingir una captura completa.
- `POST .../sessions/revoke`: recibe solo `{sessions: [...]}`, entre una y cien
  referencias, cuerpo máximo 16 KiB. Rechaza campos desconocidos, tipos
  incorrectos, duplicados, claves JSON duplicadas y datos posteriores al JSON.
  Los identificadores de sesión son opacos y acotados, no se asumen UUID.
  Valida la propiedad de todo el lote antes de la primera eliminación. Una
  referencia de otra persona deniega el lote entero.
- Una sesión ya inexistente es un no-op. La respuesta solo tiene conteos
  `removed` y `missing`. Las respuestas exitosas tienen `Cache-Control: no-store`.
  Las cuentas técnicas y otros realms quedan fuera del alcance.

Se invalida precisamente la sesión online u offline seleccionada. No se cambia
not-before de usuario/realm, contraseña, roles, consentimientos o estado enabled;
no se propaga un logout al proveedor externo ni se elimina implícitamente una
sesión contraparte. Para el RAC actual no hay backchannel de aplicación
registrado; la invalidación afecta SSO y refresh en Keycloak. Un JWT firmado
emitido antes puede seguir validando criptográficamente en una API: standing
sigue siendo el control comercial y no se sustituye por este efecto.

### Orquestación necesaria antes de activar

El worker de user debe capturar las referencias y guardarlas de forma durable
antes del primer POST. Bajo lock de la cuenta autoritativa vuelve a comprobar
que la misma versión sancionada sigue vigente y persiste la captura ligada al
evento original, con claim y fencing. Una reversión que ya se confirmó impide
guardar una captura nueva para el evento antiguo.

Una vez guardada la captura, los reintentos usan **la misma lista**, también
después de timeout, ACK perdido o reinicio; no vuelven a enumerar sesiones.
Las sesiones abiertas después de esa captura tienen otros identificadores y
quedan fuera de todos esos reintentos. Una reversión que ocurre después de la
comprobación final también ocurre después de la captura: una nueva sesión
posterior a la reversión queda fuera sin comparar relojes entre sistemas.

El worker no se declara conectado por tener el endpoint. Todavía requiere su
journal forward, identidad PostgreSQL mínima, transiciones/reintentos, métricas,
pruebas reales de carreras/reversión y wiring opt-in del stack. La función de
sanción conserva su frontera de operador y auditoría; el futuro ingreso humano
de P11 no debe ejecutar un logout global alternativo.

## Validación y activación

`python scripts/test_session_control.py` construye el proveedor real y utiliza
dos nodos Keycloak con PostgreSQL y TLS propios, Authorization Code + PKCE,
sesiones online/offline, permisos negativos, replay y reinicios. Solo crea y
elimina sus recursos aleatorios; no lee `.env` ni usa DEV.

La ejecución local del 25-10-2026 pasó los tres bloques: separación por
firma/audience/cliente/realm y permisos negativos; revocación precisa de sesiones
online/offline y replay concurrente entre nodos; reinicio con PostgreSQL
persistente, supervivencia del login nuevo y extensión inactiva por defecto.
También se verifican token expirado, rol ausente, persona con el mismo rol,
flujo de contraseña denegado y pérdida de archivo de secreto sin rotación
silenciosa. La reconciliación elimina grants/scopes administrativos directos,
composites accidentales del rol propio y membresías de grupo de la service
account. El job de migraciones ejecuta esta suite; falta su resultado remoto
para la revisión nueva.

La imagen no se incorpora todavía al stack persistente. Antes de activarla se
deben completar los gates del worker y el backup/restore de DEV. Deshabilitar o
eliminar cuentas por vencimiento de apelación/compromiso pertenece a las
decisiones y entregas correspondientes; este adaptador no puede hacerlo.
