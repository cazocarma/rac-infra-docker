# P01 — Base compartida y auditoría en DEV

Implementación local: 2026-10-22, posterior a aprobación del plan por el usuario.
No sustituye el estado histórico de la inspección de Fase 0.

Revisiones locales verificadas: platform `fd2f961` y contratos `77ade75`;
infra en rama `feat/trust-safety-foundation`, sobre el baseline indicado en
current-state. Estos cambios no están publicados ni promovidos a main.

## Entregado

- Nuevo repositorio local `rac-platform`: paquetes audit/policy y puertos
  standing/contentsignals/retention; CLI `rac-audit verify`, firma/verificación
  de checkpoints Ed25519 sin generar ni activar claves persistentes.
- Contratos JSON Schema de registro audit v1 y evento de standing v1 en
  rac-shared-contracts, ejemplos sintéticos y pruebas. El evento está preparado,
  no tiene todavía productor/consumidor ni enforcement en APIs.
- V018 forward: esquema aislado audit, cabeceras, registro, principal por login,
  función append SECURITY DEFINER con search_path fijo y permisos mínimos.
  No cambia ni borra tablas del chat. No se concede acceso a servicios existentes.
- CI del módulo Go y prueba PostgreSQL desechable añadida a CI infra;
  `make test-audit-foundation` en infra y `make test`/`make fuzz` en platform.

Ninguna API devuelve ahora este registro al usuario; no hay nuevos textos
de producto, por lo que no se introducen claves ARB antes de P04. Mensajes
CLI/diagnóstico son técnicos y no representan una notificación jurídica.

## Qué protege y qué falta

La función deriva el actor del login de **servicio**, no de un actor enviado
por la app. El contrato P01 no atribuye acciones a una persona staff. Hasta
P02 y la verificación del ingreso delegado no se habilita acceso a evidencia
basado en este formato. Los roles writer/reader son NOLOGIN y no se entregan
automáticamente. Aprovisionar un login requiere al operador/migrador, no un
endpoint del producto.

Append no permite editar/eliminar a los roles de aplicación. El dueño de BD
puede alterar datos: verify detecta cambios contra una cabecera confiable.
El anclaje independiente, claves externas, alertas y restauración siguen
pendientes de D08/D11/D14; no hay WORM ni detección operacional continua ya
activados. Un checkpoint firmado viejo puede ser válido pero obsoleto: el
custodio debe suministrar el último head confiable y controlar su frescura.

No se afirma que el corpus, KYC, suspensiones, retención, RBAC staff ni casos
estén implementados por disponer de puertos. Se incorporan en los PR siguientes.
Las decisiones jurídicas/proveedores conservan sus gates desactivados.

## Ensayos realizados

Docker Desktop pudo iniciarse durante esta implementación. Se usaron recursos
desechables con nombres únicos, sin `.env`, puertos publicados ni acceso a BD DEV.

| Ensayo | Resultado local |
|---|---|
| Go vet, go test -race, paquetes audit/adapter/CLI/policy | PASS |
| Fuzz validación de entradas del formato audit, 5 s / 2 workers | PASS (86.205 ejecuciones en la primera corrida) |
| PostgreSQL: identidad de servicio, writer/reader sin UPDATE/DELETE/TRUNCATE/DDL, login sin map denegado | PASS |
| 16 appends concurrentes + ocho reintentos del mismo event_id | PASS, sin pérdida/duplicado |
| Rollback e idempotencia/conflicto de metadata | PASS, cabecera y secuencia consistentes |
| Paridad bytes/hash entre SQL, verificador independiente Python y CLI Go | PASS |
| Edición por DBA y truncamiento del final contra head confiable | PASS, detectados |
| Migraciones fresh/legacy, preservación de datos, repetibilidad y drift | PASS; incluye regresiones de cupos, chat y publicación actual |

Los resultados corresponden a las revisiones locales de esta entrega, no a un
pipeline remoto. Las migraciones se ensayaron en copias desechables: **V018 no
se aplicó a la BD DEV**. Contratos: cuatro tests PASS y OpenAPI válido, ejecutados en un contenedor
con las dependencias fijadas de CI. Workflows: política de Actions PASS
(pins inmutables, runtimes revisados y runner explícito).

## Reproducción

```sh
# En rac-platform:
make test
make fuzz
# En rac-infra-docker, solo Docker y Python estándar:
make test-audit-foundation
python scripts/test_audit_foundation.py --go-check
python scripts/test_migrations.py
python scripts/check_actions.py --workspace ..
# En rac-shared-contracts, tras instalar las dependencias fijadas de su CI:
python -m unittest discover -s tests
```

El export NDJSON y head deben salir de un snapshot consistente. El CLI recibe
`--from` con chain_id, sequence y hash del predecesor y `--to` con la cabecera
final confiable. Para génesis: sequence 0 y hash de 64 ceros; no usar ese valor
si se verificará solo un rango intermedio. Límite por registro: 4096 bytes.

## Aplicación y reversa

Aplicar mediante el migrador existente y su historial meta solo después de
revisar la rama base y el backup. V018 necesita crear roles; el migrador debe
tener ese permiso, nunca una app. Se añade un schema sin tocar rutas activas,
por lo que volver al binario anterior no requiere borrar auditoría.

Ante fallo, no editar V018 ni ejecutar DROP del registro: corregir mediante
migración forward. Si se comenzó a escribir, preservar cadena, heads y
checkpoints antes de cualquier restauración. El alta de logins/permisos queda
para P02; no reutilizar el login compartido actual como supuesto aislamiento.

Siguiente unidad: P02, permisos DB por dueño y cuenta técnica Keycloak mínima,
con pruebas negativas y autenticación reforzada para staff. La integración de
standing se realiza después, en P03.
