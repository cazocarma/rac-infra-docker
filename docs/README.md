# Documentación general de RAC

La implementación vigente está en [OIDC, migraciones, permisos y observabilidad](implementacion-oidc.md).
Sus comprobaciones están en [validación de implementación](validacion-implementacion.md).
El inventario inicial se conserva como diagnóstico anterior a esos cambios.

Revisión: 15 de octubre de 2026. Estado inspeccionado: ramas `dev` de los 11
repositorios; las referencias exactas están en [ramas verificadas](ramas-verificadas.md).

- [Entornos, operación local y preparación de QA/PRD](ambientes.md).
- [Estado real por repositorio y alineación tecnológica](estado-repositorios.md).
- [Hallazgos y orden de trabajo](pendientes.md).
- [Validaciones realizadas y sus límites](validacion.md).

## Dónde mantener la documentación

Por ahora, `rac-infra-docker/docs` es la fuente de la documentación transversal:
arquitectura, entornos, operación y decisiones. Cambia junto con la infraestructura
y evita mantener dos versiones de las mismas instrucciones. Cada servicio debe
mantener su README con su API y desarrollo específico; `rac-shared-contracts`
debe contener los contratos ejecutables, no copiar documentación operativa.

`rac-docs` ya existe y conserva un documento Word histórico y un README vacío.
No se eliminó ni movió ese material. Conviene usarlo como referencia histórica
y enlazar esta carpeta cuando decidamos publicar esta revisión. Un repositorio
separado para documentación tendría sentido si aparece documentación extensa de
producto, una web de documentación o personas que la mantengan independientemente
de la infraestructura. Hasta entonces duplicar ambas fuentes agrega mantenimiento.

Crear ramas no equivale a desplegar un entorno ni a certificar una versión:
DEV está ejecutándose en este PC; QA y PRD tienen configuración preparada,
pero no están desplegados y conservan bloqueos explícitos.

- [Interfaz, reserva funcional y pruebas de navegador](interfaz-y-reservas.md).

- [Cupos gratuitos y suscripción de compas](cupos-y-suscripciones.md).

- [Activación gratuita de compas y permisos](activacion-compa.md).

- [Entrega y validaciones del 19 de octubre de 2026](entrega-2026-10-19.md).

- [Resolver permisos de lectura entre repositorios en CI](ci-acceso-repositorios.md).

- [Perfil personal y revisión de promoción](perfiles-y-promocion.md)
