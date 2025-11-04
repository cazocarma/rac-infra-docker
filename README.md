# 🐳 Rent-a-Compa – Infraestructura Docker

Este repositorio contiene la infraestructura base del proyecto **Rent-a-Compa**, incluyendo:
- PostgreSQL + PostGIS  
- Keycloak (autenticación y gestión de identidades)  
- RabbitMQ (mensajería)  
- MinIO (almacenamiento de archivos)  
- pgAdmin (administración de base de datos)  
- Todos los microservicios Go  
- Frontend Flutter Web  
- NGINX como reverse proxy  

---

## 📁 Estructura de Archivos

```
rac-infra-docker/
 ├── docker-compose.dev.yaml      # Stack de desarrollo
 ├── docker-compose.prd.yaml      # Stack de producción
 ├── nginx/
 │   └── nginx.conf
 └── README.md                    # Este archivo
```

Los archivos `.env.dev` y `.env.prd` se ubican **una carpeta arriba**, en el root del proyecto (`rent-a-compa/`).

---

## 🚀 Inicio Rápido (Entorno de Desarrollo)

1. **Ir al directorio de infraestructura**
   ```bash
   cd rac-infra-docker
   ```

2. **Verificar que exista el archivo `.env.dev`**
   ```bash
   ls ../.env.dev
   ```
   Si no existe, crea una copia del ejemplo:
   ```bash
   cp ../.env.dev ../.env
   ```

3. **Construir y levantar el stack**
   ```bash
   docker compose -f docker-compose.dev.yaml up -d --build
   ```

4. **Verificar que todo esté corriendo**
   ```bash
   docker ps
   ```

   Deberías ver contenedores como:
   ```
   rac-postgres, rac-keycloak, rac-minio, rac-rabbitmq,
   rac-auth, rac-user, rac-match, rac-chat,
   rac-payment, rac-alert, rac-admin, rac-frontend, rac-nginx
   ```

---

## 🧠 Servicios Principales (Dev)

| Servicio       | URL local                          | Descripción |
|----------------|------------------------------------|--------------|
| **Frontend**   | [http://localhost](http://localhost) | Flutter Web |
| **Keycloak**   | [http://localhost:8081](http://localhost:8081) | Administración de usuarios y roles |
| **pgAdmin**    | [http://localhost:5050](http://localhost:5050) | Interfaz para PostgreSQL |
| **RabbitMQ UI**| [http://localhost:15672](http://localhost:15672) | Consola de mensajería |
| **MinIO UI**   | [http://localhost:9001](http://localhost:9001) | Consola de archivos |
| **Microservicios** | `/health` endpoints en `http://localhost/api/<svc>/health` | Verificación básica de cada servicio |

---

## 🩺 Verificar los Servicios

Ejemplo para comprobar cada servicio:

```bash
curl http://localhost/api/auth/health
curl http://localhost/api/user/health
curl http://localhost/api/match/health
curl http://localhost/api/chat/health
curl http://localhost/api/payment/health
curl http://localhost/api/alert/health
curl http://localhost/api/admin/health
```

Salida esperada:

```json
{"status":"ok","service":"rac-user-service"}
```

---

## 🧰 Comandos de Mantenimiento

### 📦 Reconstruir todo el stack
```bash
docker compose -f docker-compose.dev.yaml up -d --build
```

### 🧹 Detener y eliminar contenedores
```bash
docker compose -f docker-compose.dev.yaml down
```

### 🔥 Detener, eliminar y limpiar volúmenes
```bash
docker compose -f docker-compose.dev.yaml down -v
```

### 🗂️ Ver logs de un servicio
```bash
docker logs -f rac-user
```

---

## 🧾 Inicialización del Entorno (solo la primera vez)

1. **Ingresar a Keycloak:**
   - URL: [http://localhost:8081](http://localhost:8081)
   - Usuario: `admin`
   - Contraseña: `admin`
   - Crea el **realm** `rentacompa`
   - Crea los **roles**: `cliente`, `compa`, `admin`
   - Crea el **client** `frontend` con acceso público (PKCE o confidencial)

2. **Ingresar a pgAdmin:**
   - URL: [http://localhost:5050](http://localhost:5050)
   - Usuario: `admin@rentacompa.local`
   - Contraseña: `admin123`
   - Agrega un nuevo servidor:
     - **Name:** Rentacompa Dev  
     - **Host:** `postgres`  
     - **Port:** `5432`  
     - **User:** `postgres`  
     - **Password:** `postgres`

3. **Acceso a MinIO:**
   - URL: [http://localhost:9001](http://localhost:9001)
   - Usuario: `minio`
   - Contraseña: `minio123`
   - Crea el bucket `media-dev`

---

## ☁️ Despliegue en Producción

1. **Asegúrate de tener `.env.prd` configurado**
   ```bash
   ls ../.env.prd
   ```

2. **Ejecutar el stack de producción**
   ```bash
   docker compose -f docker-compose.prd.yaml up -d
   ```

3. **Verificar servicios activos**
   ```bash
   docker ps
   ```

---

## ⚙️ Tips de Administración

- Para reiniciar solo un servicio:
  ```bash
  docker compose -f docker-compose.dev.yaml restart rac-user
  ```

- Para reconstruir solo un servicio:
  ```bash
  docker compose -f docker-compose.dev.yaml up -d --build rac-user
  ```

- Para limpiar imágenes antiguas:
  ```bash
  docker image prune -f
  ```

---

## 🧾 Healthchecks de Base

Todos los microservicios exponen:
```
GET /health → {"status":"ok","service":"<nombre-servicio>"}
```

NGINX enruta internamente:
```
/api/auth/health
/api/user/health
/api/match/health
/api/chat/health
/api/payment/health
/api/alert/health
/api/admin/health
```

---

## 🧹 Limpieza Total del Entorno (opcional)

Si deseas eliminar **todos los volúmenes** y datos (incluyendo Postgres, MinIO y Keycloak):

```bash
docker compose -f docker-compose.dev.yaml down -v
docker volume rm rac-infra-docker_pgdata rac-infra-docker_minio-data rac-infra-docker_keycloak-data rac-infra-docker_rabbitmq-data
```

⚠️ **Esto borra toda la información persistente.**

---

## 📚 Notas finales

- El stack completo puede tardar entre **1 y 2 minutos** en inicializar todos los contenedores (especialmente Keycloak y Postgres).  
- Asegúrate de que los puertos **80, 5432, 8081, 5050, 9000, 9001, 15672** estén libres antes de iniciar.  
- Para entornos remotos, los archivos `.env.prd` deben gestionarse con **AWS Secrets Manager** o variables protegidas en CI/CD.  
- Todos los contenedores pertenecen a la red `rac-net`, lo que permite comunicación interna por nombre de servicio.

---

🧡 **Rent-a-Compa — Arquitectura Docker Multiservicio**
