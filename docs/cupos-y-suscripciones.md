# Cupos gratuitos y suscripción de compas

Regla acordada: ser compa no exige pagar por anticipado. Recibir solicitudes no consume cupos; confirmar una reserva sí. Cada compa dispone de tres confirmaciones gratuitas por semana, de lunes a domingo, según la fecha de inicio de la actividad en `America/Santiago`, con cambio de hora de Chile incluido.

Una cuarta aceptación sin suscripción activa devuelve HTTP 402 `subscription_required`. La reserva permanece pendiente; el cliente sigue viendo «Pendiente de aceptación». La interfaz del compa informa el límite y abre la explicación de planes. Activar una suscripción nunca aceptará solicitudes automáticamente.

Cancelar antes de iniciar devuelve el cupo de la semana correspondiente. Cancelar después del inicio no lo devuelve. Las reservas finalizadas conservan su consumo. Reintentar una aceptación ya confirmada no consume dos veces. La regla también se aplica si un administrador acepta en nombre del compa.

## Implementación

- Migración `V004__weekly_compa_allowance.sql`: registro persistente por reserva confirmada y tabla de derechos de suscripción. Adopta las reservas activas/finalizadas existentes; no modifica V001–V003.
- Aceptaciones y cancelaciones se serializan por compa con un bloqueo transaccional PostgreSQL. Verificar el límite, consumir/restituir cupo y cambiar estado forman una sola transacción. Solicitudes simultáneas no pueden superar tres cupos gratuitos.
- `GET /api/match/compa/{id}/allowance?fecha=YYYY-MM-DD` devuelve la semana, usados, disponibles y derecho activo. Solo el propio compa o un admin pueden consultarlo. El identificador es el del usuario de dominio.
- Los derechos se consultan al aceptar: estado activa y período vigente. No existe endpoint para que el cliente active su plan ni suscripciones demo. El precio, renovación, cancelación/reembolsos del plan y proveedor de pago siguen pendientes de conversación. No hay cobros ni checkout simulado.

La integración futura de pagos deberá verificar la notificación del proveedor, aplicar idempotencia y registrar el derecho en `compa_suscripcion`. Un redirect del navegador no podrá activar permisos. Las reservas ya aceptadas no se cancelarán por vencer una suscripción.

## Alcance pendiente

El flujo gratuito de creación/publicación de un perfil compa está implementado en Sé Compa, incluyendo habilidades, tarifa referencial y disponibilidad con zona IANA. Véase [activación-compa.md](activacion-compa.md). Las solicitudes sin aceptar vencen al llegar su hora de inicio mediante booking-maintenance. La falta de pago no las rechaza anticipadamente ni acepta automáticamente al pagar. Véase [agenda y vencimientos](dashboard-administrativo.md).

## Verificación

`test_migrations.py` usa PostgreSQL desechable y ejecuta el test Go del repositorio: ocho aceptaciones paralelas producen exactamente tres confirmadas, cinco bloqueadas; verifica restitución antes del inicio, consumo tras cancelación tardía, cambio de semana en Chile, reintento y derechos de suscripción activos/cancelados. Solo el test aislado inserta derechos de suscripción.

Las pruebas Flutter verifican el manejo de HTTP 402. La prueba de navegador intercepta una respuesta 402 exclusivamente para comprobar el aviso y la navegación a planes; luego retira la interceptación y acepta/cancela contra la API real. La autorización del endpoint de cupos se prueba con tokens OIDC reales en DEV.

## Resultado en DEV — 15 de octubre de 2026

V004 aplicada tras guardar `.local/backups/rentacompa-before-weekly-allowance.sql`.
Go vet/race, migración fresca/adopción/checksum, once pruebas Flutter, OpenAPI y
smoke pasaron. La API real aceptó tres reservas, devolvió 402 al intentar la cuarta,
conservó su estado pendiente y permitió aceptarla tras cancelar anticipadamente una
de las anteriores. Las reservas creadas por la prueba se eliminaron por sus UUID
exactos; no se alteraron reservas ajenas. El navegador pasó login/recarga, aviso de
cupo, planes, aceptación/cancelación y logout en escritorio y móvil.
