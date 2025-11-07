-- 1) Crear rol 'keycloak' (idempotente)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'keycloak') THEN
    CREATE ROLE keycloak LOGIN PASSWORD 'keycloak';
  END IF;
END $$;

-- 2) Crear DB 'keycloak' (idempotente, SIN usar DO/función)
-- \gexec ejecuta el resultado del SELECT como SQL si la fila existe
SELECT 'CREATE DATABASE keycloak OWNER keycloak'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'keycloak')\gexec

-- 3) Conectarse a la nueva DB
\connect keycloak

-- 4) Crear schema 'kc' y permisos (idempotente)
CREATE SCHEMA IF NOT EXISTS kc AUTHORIZATION keycloak;
ALTER SCHEMA kc OWNER TO keycloak;
GRANT USAGE ON SCHEMA kc TO keycloak;

ALTER DEFAULT PRIVILEGES IN SCHEMA kc GRANT ALL ON TABLES   TO keycloak;
ALTER DEFAULT PRIVILEGES IN SCHEMA kc GRANT ALL ON SEQUENCES TO keycloak;
