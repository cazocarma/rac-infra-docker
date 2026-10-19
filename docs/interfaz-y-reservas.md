# Interfaz y reservas — revisión DEV, 15 de octubre de 2026

Interfaz Material 3 con paleta violeta, modos claro/oscuro, navegación lateral en escritorio y navegación inferior/menú en móvil. Explorar incluye filtros por habilidad, tarjetas, carga, reintento y estado vacío; el contenido se desplaza completo para permitir pantallas pequeñas. Los perfiles de compas muestran información real de la API.

## Reserva funcional

La pantalla anterior proponía la hora actual y permitía confirmar un horario que ya había pasado. Ahora parte de mañana, consulta disponibilidad del compa, ofrece franjas futuras de 30 minutos que permiten la duración elegida y mantiene deshabilitado el envío hasta seleccionar una franja. Muestra fechas de inicio y término, incluso si cambia el día, valor referencial y aviso de que no hay cobro. El servidor vuelve a validar disponibilidad y colisiones al enviar. El perfil heredado «Compa Demo» no tiene disponibilidad publicada y se informa sin simular horarios; `compa1` y `compa2` sí permiten probar el recorrido en DEV.

La disponibilidad semanal tiene una zona IANA por compa. El servidor calcula los inicios disponibles respetando cambios de hora y solicitudes pendientes/reservas activas; la UI muestra la hora local del dispositivo y envía instantes UTC. Una reserva concurrente aún puede producir una colisión, que devuelve un aviso para elegir otra franja. La agenda permite aceptar solicitudes recibidas, cancelar con confirmación y finalizar reservas que ya comenzaron. Errores y carga se muestran al usuario.

## Secciones pendientes

Mensajes muestra «En construcción». Sé Compa permite activación gratuita sin aprobación, edición de descripción, tarifa, habilidades y disponibilidad semanal con zona IANA; renueva la sesión OIDC para usar el rol compa. Planes explica la regla de tres reservas semanales y muestra cupos reales por semana para compas. El checkout sigue en construcción. Mi perfil muestra nombre, correo y rol reales desde `/api/user/me`; la edición de datos, biografía y foto está señalada como pendiente. Se retiró el guardado ficticio de perfil en preferencias locales y las estadísticas ficticias de postulación. Configuración permite cambiar apariencia; las demás preferencias están en construcción. No se implementaron cobros ni dashboards de administración de producto. La activación gratuita asigna únicamente compa; no existe una solicitud para obtener admin.

## Validación

- Flutter analyze sin observaciones; 9 pruebas Flutter, incluyendo login y manejo de cupos; las pruebas de horarios/DST se ejecutan en Go, donde se calculan los slots.
- Build web release y actualización del contenedor DEV.
- Prueba Chromium real: cliente inicia sesión, reserva con un compa de demostración, compa acepta, cliente consulta y cancela; móvil abre perfil/reserva y aviso de construcción; logout sin tokens heredados en almacenamiento local.
- Capturas de escritorio y móvil en `.local/ui-review` del workspace al ejecutar desde su raíz. Móvil es una vista web de 390×844 y 320×568, no una prueba nativa en teléfono físico.

Ejecutar `scripts/test_browser.py` con Playwright instalado y Chromium disponible. `RAC_BROWSER_URL` permite cambiar la URL; `RAC_BROWSER_ARTIFACTS` define el directorio de capturas. Requiere exclusivamente DEV con las cuentas de demostración. La prueba cancela la reserva exacta que crea, incluso si una comprobación posterior falla. No elimina datos anteriores.

Cambios locales; sin commits ni push.

## Corrección del retorno de login

Se sustituyó el acceso web en otra pestaña por navegación en la misma pestaña,
con retorno a la raíz de RAC y recuperación/provisión de sesión durante el arranque.
El callback no intenta cerrar una pestaña sin `window.opener`; ofrece «Volver a RAC»
si llega una respuesta sin transacción válida. El flujo tiene tiempos máximos para
mostrar reintento en lugar de esperar indefinidamente.

La sesión web usa `OidcWebStore` con cifrado obligatorio, necesario para conservar
state/PKCE durante la navegación. Se verificó login real en el navegador integrado
hasta `/#/home`, sin cierre de pestaña. Chromium comprueba también recarga de página,
logout, almacenamiento sin JWT en texto plano y recorrido de reservas. Véase
`implementacion-oidc.md` para los detalles del almacenamiento.

Un callback con state ausente, ya consumido o inválido vuelve automáticamente a
la raíz, sin canjear ese código. La app restaura una sesión válida existente o
muestra login. No requiere pulsar «Volver a RAC». La prueba de navegador cubre
la reapertura de un callback consumido.

## Cupos y notificaciones internas

Mis reservas, en la pestaña Solicitudes recibidas, y Planes consultan el cupo real del backend. Permiten elegir una fecha para consultar su semana en Chile y actualizar la consulta. La suscripción se muestra solo si existe un derecho activo verificado en la base de datos; no hay activación ni cobro desde la interfaz.

Notificaciones lista nuevas solicitudes y cambios de estado de las reservas, con paginación, actualización, lectura persistente y acceso a Mis reservas. Solo el destinatario puede consultar o marcar sus avisos; el rol admin no permite acceder a los de otras personas. No hay correo, push ni actualización automática en tiempo real. Ver mis reservas abre la agenda completa, no una reserva individual.

La migración V005 crea `notificacion` y un trigger transaccional en `sesion`. Este enfoque aprovecha la base compartida actual: si la reserva se revierte no queda un aviso falso, y una actualización sin cambio de estado no duplica notificaciones. No se generan avisos históricos. Al separar bases por microservicio habrá que trasladar esta responsabilidad a eventos con outbox y consumo idempotente en alert-service; ese servicio todavía no implementa entrega.

Validación de esta entrega: migración V005 aplicada en DEV tras respaldo local; migraciones en base desechable, Go vet/race, OpenAPI y pruebas de integración real con OIDC, privacidad de avisos y lectura idempotente.

Chromium verificó login, reserva, aceptación, cancelación, contador en Planes y notificaciones con lectura real. Capturas `plans-allowance.png` y `mobile-notifications.png` (320×568) en `.local/ui-review`.

Sé Compa: ver [activación y permisos](activacion-compa.md). Prueba real Chromium de creación de perfil y renovación de sesión, edición persistente y agenda con tres cupos; identidad temporal eliminada al finalizar. No se promocionaron las cuentas cliente1/cliente2 utilizadas por las otras pruebas.
