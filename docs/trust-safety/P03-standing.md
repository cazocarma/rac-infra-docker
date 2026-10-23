# P03 — Estado de cuenta (en desarrollo)

D02 y D03 fueron confirmadas por el usuario el 22 de octubre de 2026.
La matriz y el alcance del cupo están en [ADR-001](ADR-001-standing.md).

## Entrega local: motor compartido

`rac-platform/standing` implementa evaluación de capacidades y restricciones
temporales. Mantiene canales de protección aun con cuenta suspendida/baneada o
autoridad indisponible. La excepción requiere autenticación y propiedad en cada
adaptador; no concede acceso a recursos ajenos.

Los leases duran como máximo dos segundos desde el inicio de la petición a la
autoridad, consumiendo la latencia de red. Una versión posterior invalida el
lease; eventos antiguos no lo prolongan. Se copian las restricciones para que
el llamador no pueda mutar una autorización emitida. El adaptador deberá usar
reloj monotónico local y no reconstruir leases desde timestamps del broker.

`AuthorityAuthorizer` ofrece el camino síncrono sin caché: consulta una fuente
autenticada y su versión más reciente. Niega operaciones comerciales ante error,
versión ausente o respuesta tardía, sin filtrar diagnósticos privados. La fuente
concreta todavía no está conectada. El resultado no sustituye el control de
versión y autorización al commit de la operación de negocio.

El contrato todavía no publicado de `user.standing.changed.v1` incluye las cinco
capacidades nuevas y exige los siete canales de protección en todos los estados.
Suspensión/ban no pueden anunciar permisos comerciales.

## Entrega local: persistencia de autoridad V020

`standing.account` referencia al usuario real y conserva versión monotónica.
V020 inicializa usuarios existentes como active/version 1 y un trigger crea el
estado de nuevos usuarios dentro de su transacción. No modifica roles Keycloak.
Las restricciones solo pueden afectar las cinco capacidades comerciales; los
canales de protección no se pueden restringir por esta vía.
El estado inicial sigue el ciclo de vida de usuario mediante FK en cascada. Un
usuario con eventos de enforcement no puede borrarse físicamente por esa vía:
la referencia restrictiva del outbox impide eliminar su historial. Esto no define
plazos legales de retención ni sustituye el futuro flujo de privacidad.

`standing.change_account` bloquea la fila, exige versión esperada y guarda estado,
restricciones, auditoría y outbox en la misma transacción. Event ID repetido con
el mismo comando devuelve el evento original; contenido diferente o versión
obsoleta falla. Los registros de comando contienen solo referencias, estados,
capacidades y fechas; no aceptan una justificación privada libre.

La función no se concede a roles de aplicación. Un principal de auditoría debe
estar provisionado para el login autenticado o toda la transacción falla. No se
activa una API de sanciones antes de conectar autorización staff, revisión de
casos y política aprobada. El actor auditado sigue siendo el servicio, no una
persona staff verificada.

Solo rac_user lee la autoridad; otros servicios no reciben acceso a esas tablas.
`rac-platform/standing/postgres` proporciona el adaptador de lectura del dueño:
liga el subject OIDC a usuario, obtiene estado/restricciones en un snapshot SQL y
devuelve errores opacos. El publicador y los consumidores aún no están conectados.
El respaldo tiene lectura y el bootstrap incluye el nuevo esquema al reconciliar
propiedad, sin ampliar permisos de otros servicios.

## Entrega local: efectos de reservas V021

Match mantiene inbox, proyección monotónica y efectos en tablas propias.
`Repositorio.ApplyStanding` recibe una entrada interna validada por el futuro
consumidor autenticado, no una petición HTTP. La huella del inbox cubre la entrada
semántica de match (evento, usuario, versión y estado); el transporte deberá
validar el contrato completo. Las entregas duplicadas se confirman sin repetir
efectos; un mismo evento con contenido distinto o misma versión con estado
contradictorio falla. Versiones anteriores no revierten la proyección.

Suspensión/ban cancela pendientes y activas cuyo inicio aún es futuro al procesar
el evento. La comparación usa el reloj de PostgreSQL después de bloquear las
reservas, no la fecha de emisión ni el reloj del consumidor. Si el sancionado es
cliente, restituye el registro de cupo de su compa contraparte sin cambiar la
semana original. Si es compa, no devuelve su propio cupo. Una activa ya iniciada
conserva estado y genera un efecto durable `safety_review`, todavía pendiente de
ingreso al módulo de casos. Las finalizadas y canceladas permanecen intactas.

Los efectos, cambios de estado, devolución, inbox y proyección confirman juntos;
la cancelación genera el evento de reservas mediante el trigger existente.
Se toma el mismo lock de proveedor que usa la aceptación de cupos. Una reversión
solo actualiza la proyección; no reactiva ninguna reserva.

Esta entrega no activa un worker RabbitMQ ni protege por sí sola las nuevas
reservas creadas durante entrega tardía. Falta el control autoritativo en las
escrituras, su comprobación al commit y reconciliación. La proyección no es un
lease fresco y no debe usarse para autorizar operaciones por sí sola.
El manifiesto integrado fija el commit local de match con estas pruebas. Antes
de publicar infra se deben publicar también las revisiones de servicios fijadas;
este expediente no acredita que GitHub pueda descargarlas todavía.

## Evidencia local

- Go 1.27.2 en contenedor: `gofmt`, `go vet ./...`, `go test -race ./...`.
- Pruebas de estados desconocidos, restricciones malformadas, límites temporales,
  modificación de snapshots, autoridad caída/lenta, versión obsoleta y protección.
- Contratos: suite Python con `jsonschema[format]==4.25.1`, contenedor desechable.
- Desde RAC: `make -C rac-infra-docker test-standing-authority`: PostgreSQL desechable, rollback por auditoría
  ausente, replay, conflictos, restricciones inválidas, concurrencia y grants.
  La prueba también está incorporada al workflow de CI; no implica ejecución
  remota ni activación en DEV.
- Suite de migraciones: instalación fresca, adopción de usuarios existentes,
  checksum y regresiones de cupos, chat y alta de compa.
- Suite de permisos: migrador sin superusuario, reconciliación del esquema
  standing, lecturas limitadas al dueño y respaldo/restauración con ACL.
- Match Go: `go vet ./...`, `go test -race ./...`; en PostgreSQL desechable,
  sanción de cliente versus compa, futuras versus iniciadas/finalizadas,
  devolución a contraparte, fallo a mitad de transacción, entrega duplicada en
  paralelo, ID/versión contradictorios y reversión seguida de evento antiguo.

## Pendiente para completar P03

1. Publicación privada y versión fijada del módulo, acceso mínimo de CI y builds
   reproducibles sin secretos en capas Docker ni `replace` local permanente.
2. Conectar la autoridad al ingreso autenticado de staff y a políticas aprobadas;
   transporte autenticado, publicación del outbox e inbox por consumidor.
3. Integración de todos los escritores y contrapartes, catálogo y medios,
   invalidación/reconciliación, controles al commit y aviso en Flutter.
4. Conectar los efectos de reservas al consumidor autenticado y al módulo de casos;
   probar integración con los controles autoritativos concurrentes.
5. Pruebas E2E con JWT anterior, particiones, dos instancias y carreras, además
   de medición de latencia bajo carga definida.

No hay enforcement nuevo activo en las APIs ni migraciones P03 aplicadas a DEV.
Las pruebas unitarias no prueban el objetivo de revocación p99 de cinco segundos.
