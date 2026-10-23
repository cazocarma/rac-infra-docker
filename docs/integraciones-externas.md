# Preparación de integraciones externas

El usuario autorizó preparar integraciones, sin activar proveedores ni realizar
cobros, envíos externos o copias fuera del PC. Ninguna pantalla debe anunciar
éxito de pago/envío/copia hasta recibir confirmación real de su proveedor.

## Suscripciones y pagos

Pendientes de acordar: proveedor, moneda/precio del plan, período, renovación,
cancelación y reembolsos. Contratar tiempo de un compa y pagar una suscripción son
operaciones distintas. No crear planes ficticios ni activar derechos desde el
redirect del navegador. `rac-payment-service` sigue sin checkout operativo.

Contrato de implementación: crear orden local con referencia UUID y clave
idempotente por intento; crear checkout desde servidor con importe del catálogo;
verificar firma, antigüedad y cuerpo bruto del webhook antes de registrar su ID
único. Guardar recepción, transición válida y evento de derecho en una transacción;
ACK solo tras commit. Reintentos/orden inverso no deben duplicar cargos ni derechos.
Consultar el estado autorizado al proveedor para reconciliar eventos faltantes.
El evento debe incluir referencia de pago, compa, período UTC y estado, nunca
PAN/CVV, tokens del proveedor ni datos personales en logs/RabbitMQ.

No conectar webhooks públicos ni secretos de sandbox hasta elegir proveedor y
validar su contrato oficial. Antes de activar: sandbox aprobado de éxito, rechazo,
duplicado, firma inválida, devolución y reconciliación tras corte.

## Correo y push

La bandeja privada es la fuente durable actual. La entrega externa debe ser un
consumidor separado con cola de reintentos y DLQ, sin bloquear reservas. Guardar
entrega por (evento, canal, destinatario) con clave única y referencia externa;
respetar preferencias y revocación de dispositivos, separar aviso de marketing.
La aceptación del proveedor no equivale a lectura; reflejar estados reales.

Correo requiere proveedor/dominio remitente y su configuración DNS; push requiere
proyecto y credenciales de plataforma, consentimiento y tokens por dispositivo.
Enviar avisos mínimos con enlace autenticado; no incluir conversaciones, detalles
de reportes ni credenciales. Primero probar con sumidero local y dispositivos de
prueba, sin envíos a contactos reales. Faltan proveedores elegidos y esas pruebas.

## Respaldo externo

La copia local cifrada y restauración aislada existen; no se ha configurado un
destino fuera del PC. Elegir destino independiente del disco local, región,
retención, cuota y credencial dedicada. El destino debe recibir respaldos cifrados;
no sincronizar borrados de datos de producción directamente sobre el respaldo.
Separar y custodiar contraseña de recuperación y credenciales del repositorio.

Antes de activarlo, copiar un respaldo de prueba al destino, recuperar desde ese
destino en almacenamiento vacío y verificar base RAC, Keycloak y fotos. Registrar
fecha/resultado, tamaño y antigüedad del último éxito sin rutas secretas ni claves.
No declarar recuperación probada a partir de un simple upload HTTP 200.

## QA y permisos de base de datos

No hay host productivo configurado. El overlay por sí solo no acredita un despliegue.
Antes de publicar: separar login/roles por propietario (runtime sin CREATE/ALTER,
migrador separado); inventariar tablas leídas por chat, reseñas y cupos antes de
revocar; convertir lecturas cruzadas en contratos o proyecciones verificadas.
Admin ya usa APIs y no requiere permisos de BD. Probar rechazo explícito de DDL y
escrituras fuera del dominio en bases desechables antes de cambiar DEV.

La entrega QA debe usar imágenes por digest, URLs OIDC/TLS y secretos propios;
probar login, agenda, reserva, mensajes, alertas y restauración. Solo una evidencia
QA exitosa para los mismos artefactos habilita el gate PRD existente. La ampliación
de aislamiento y el ensayo sobre un host real siguen siendo trabajo pendiente.
