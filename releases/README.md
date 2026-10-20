# Manifiestos de entrega

Crear `<release-id>.json` después de que los cinco pipelines de aplicación
publiquen sus imágenes y entreguen los artefactos `image-digest`. Ejemplo de
estructura (los digests deben ser los reales; no publicar esta plantilla como entrega):

```json
{
  "AUTH_IMAGE": "ghcr.io/cazocarma/rac-auth-service@sha256:<digest>",
  "USER_IMAGE": "ghcr.io/cazocarma/rac-user-service@sha256:<digest>",
  "CHAT_IMAGE": "ghcr.io/cazocarma/rac-chat-service@sha256:<digest>",
  "MATCH_IMAGE": "ghcr.io/cazocarma/rac-match-service@sha256:<digest>",
  "FRONTEND_IMAGE": "ghcr.io/cazocarma/rac-frontend-flutter@sha256:<digest>"
}
```

El manifiesto se revisa por PR y se promueve sin cambiar las cinco referencias.
El host debe tener esas mismas referencias en su archivo de entorno.
El workflow requiere confirmación explícita, reviewers del GitHub Environment
y, para PRD, un registro exitoso de QA con el mismo manifiesto.
