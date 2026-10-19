-- 0001_keycloak_db.sql
-- Crea rol y DB para Keycloak (idempotente)

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'keycloak') THEN
    CREATE ROLE keycloak LOGIN PASSWORD 'keycloak';
  END IF;
END $$;

SELECT 'CREATE DATABASE keycloak OWNER keycloak'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'keycloak')\gexec

\connect keycloak

CREATE SCHEMA IF NOT EXISTS kc AUTHORIZATION keycloak;
ALTER SCHEMA kc OWNER TO keycloak;
GRANT USAGE ON SCHEMA kc TO keycloak;

ALTER DEFAULT PRIVILEGES IN SCHEMA kc GRANT ALL ON TABLES TO keycloak;
ALTER DEFAULT PRIVILEGES IN SCHEMA kc GRANT ALL ON SEQUENCES TO keycloak;
