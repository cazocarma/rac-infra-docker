# Identidad visual y revisión local

RAC usa verde profundo (#183F31), verde de acción (#176B58), superficies claras cálidas y acentos suaves para actividades. El tema oscuro conserva contraste y la preferencia del dispositivo. No se añaden perfiles, opiniones ni estados de disponibilidad ficticios.

## Flutter

Los tokens viven en `lib/shared/widgets/design.dart` y la marca y composición decorativa en `lib/shared/widgets/brand.dart` del frontend. Login, exploración, navegación, perfiles y planes comparten esos componentes. Reservas, onboarding y notificaciones conservan sus flujos reales. Mensajes implementa conversación privada, seguridad y moderación. El checkout de pagos continúa en construcción. Los layouts ajustan columnas y espaciado a pantallas estrechas.

## Keycloak local

El tema `keycloak/themes/rac/login` extiende el tema nativo `keycloak`. Solo agrega CSS; no copia templates de autenticación ni incorpora scripts o fuentes externas. Por ello también se aplica a registro, recuperación y errores del proveedor. Sigue las preferencias clara/oscura del navegador; la preferencia guardada dentro de Flutter es local a la app y no se comparte entre orígenes.

El overlay DEV monta el directorio como solo lectura. `make identity-config` selecciona `rac` en el realm existente y establece español como idioma predeterminado, manteniendo inglés disponible. Importar un realm existente no actualiza sus propiedades: por eso la selección también forma parte del configurador idempotente. No cambia las políticas OIDC, los permisos ni las contraseñas.

El overlay DEV desactiva únicamente las cachés del tema, para que sus cambios se vean al recargar. Al agregar el montaje por primera vez se recrea Keycloak y se ejecuta identity-config. QA/PRD conservarán sus cachés habilitadas por defecto. Antes de usarlo en QA/PRD se deberá empaquetar el tema en una imagen versionada de Keycloak y seleccionarlo en su configuración; los overlays de release no montan el directorio DEV. No hay servidor productivo configurado en este PC.

Verificar login correcto e incorrecto, registro, recuperación, regreso a RAC, reserva y onboarding, en escritorio y móvil. Las pruebas de recuperación solo comprueban presentación y validación; la entrega de correo requiere SMTP, que no se configura con este cambio.

Referencia: [temas de Keycloak](https://www.keycloak.org/ui-customization/themes).

## Actualización de archivos web

La imagen del frontend añade un identificador derivado del contenido compilado a las solicitudes de bootstrap y main.dart.js. Nginx exige revalidación de los recursos web (`Cache-Control: no-cache`), conservando `no-store` en configuración y callback. Esto evita mezclar HTML nuevo con JavaScript de la versión anterior. No se agrega soporte offline ni un service worker propio.

Referencia: [caché y despliegue web de Flutter](https://docs.flutter.dev/platform-integration/web/faq).
