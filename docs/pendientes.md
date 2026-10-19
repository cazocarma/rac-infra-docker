# Orden de trabajo propuesto

> Diagnóstico/preparación inicial. Ver [implementación vigente](implementacion-oidc.md) para los cambios posteriores.

## Antes de considerar QA funcional

1. Acordar un contrato de auth y errores en `rac-shared-contracts` y adaptar
   backend/frontend. Elegir OIDC con PKCE o fachada y justificar el JWT interno;
   evitar implementar dos flujos de identidad parcialmente conectados.
2. Incorporar migraciones versionadas. Corregir `sesion`, aplicar la evolución
   de perfiles a volúmenes existentes y alinear IDs de PostgreSQL/Keycloak.
   Ensayar desde base vacía y desde el esquema que conserva este PC.
3. Definir permisos por endpoint: propietario de perfil/skills, roles, lectura
   de disponibilidad y acceso a reservas. Resolver mappers de roles sin fallback
   que conceda permisos por ausencia de información.
4. Sustituir el widget test de plantilla y agregar pruebas de login, perfil,
   reserva, cambios de estado y errores; tests de contrato entre servicios.
5. Agregar CI de compilación, tests y publicación por SHA; ensayar una entrega
   completa en QA antes de promover a PRD.

## Antes de PRD

- Actualizar versiones soportadas en un cambio dedicado y fijar imágenes por
  digest. Completar secretos, dominios y proxy TLS del host; definir backups,
  restauración, migraciones y rollback, con verificación real.
- Separar usuarios/permisos de base de datos: hoy los servicios comparten una
  conexión privilegiada. Revisar que logs no impriman DATABASE_URL con contraseña.
- Revisar tokens persistidos en navegador, vencimiento/refresh y modelo de sesión;
  CORS de auth está fijado a localhost y los demás servicios usan `*`.
- Sacar secretos demo de cualquier uso real. Hay material sensible histórico
  en MAIN; no se copiaron secretos de proveedores a esta documentación ni se
  reescribió el historial. Si alguno fue real, revisar su vigencia y rotación.
- Completar observabilidad y readiness de dependencias. Un HTTP 200 en health
  no prueba autorización, esquema, entrega de eventos ni consistencia de negocio.
- Elegir una imagen/distribución disponible para MinIO si se necesita storage.
  Chat, pagos, alertas y administración requieren implementación y contratos.

## Decisiones de arquitectura

Mantener por ahora Go/Gin y Flutter. En un proyecto de aprendizaje es válido
practicar microservicios; conviene terminar un recorrido vertical pequeño
`login → perfil → compas → reserva` antes de desarrollar los cuatro esqueletos.
Documentar propiedad de datos, sincronía/eventos y tolerancia a fallos. Si la
complejidad empieza a dominar el aprendizaje, evaluar un monolito modular
con esos límites explícitos como alternativa, sin rehacer el stack de inmediato.

La documentación general vive en infra/docs; contratos en shared-contracts;
documentación específica junto a cada servicio. `rac-docs` queda histórico.
