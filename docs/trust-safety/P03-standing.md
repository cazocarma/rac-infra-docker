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

## Evidencia local

- Go 1.27.2 en contenedor: `gofmt`, `go vet ./...`, `go test -race ./...`.
- Pruebas de estados desconocidos, restricciones malformadas, límites temporales,
  modificación de snapshots, autoridad caída/lenta, versión obsoleta y protección.
- Contratos: suite Python con `jsonschema[format]==4.25.1`, contenedor desechable.

## Pendiente para completar P03

1. Publicación privada y versión fijada del módulo, acceso mínimo de CI y builds
   reproducibles sin secretos en capas Docker ni `replace` local permanente.
2. Tablas de autoridad/restricciones y actualización transaccional con auditoría
   y outbox, transporte autenticado e inbox por consumidor.
3. Integración de todos los escritores y contrapartes, catálogo y medios,
   invalidación/reconciliación, controles al commit y aviso en Flutter.
4. Cancelación futura idempotente y devolución de cupo a contraparte; actividad
   iniciada a revisión y reversión sin resucitar reservas.
5. Pruebas E2E con JWT anterior, particiones, dos instancias y carreras, además
   de medición de latencia bajo carga definida.

No hay enforcement nuevo activo en las APIs ni migraciones P03 aplicadas a DEV.
Las pruebas unitarias no prueban el objetivo de revocación p99 de cinco segundos.
