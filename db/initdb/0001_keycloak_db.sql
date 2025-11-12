-- 0001_keycloak_db.sql
-- Reinicia la base y el esquema KC en cada arranque

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_database WHERE datname = 'keycloak') THEN
    PERFORM pg_terminate_backend(pid)
    FROM pg_stat_activity
    WHERE datname = 'keycloak' AND pid <> pg_backend_pid();
    EXECUTE 'DROP DATABASE keycloak';
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'keycloak') THEN
    CREATE ROLE keycloak LOGIN PASSWORD 'keycloak';
  END IF;
END $$;

CREATE DATABASE keycloak OWNER keycloak;

\connect keycloak

DROP SCHEMA IF EXISTS kc CASCADE;
CREATE SCHEMA kc AUTHORIZATION keycloak;
ALTER SCHEMA kc OWNER TO keycloak;
GRANT USAGE ON SCHEMA kc TO keycloak;

ALTER DEFAULT PRIVILEGES IN SCHEMA kc GRANT ALL ON TABLES TO keycloak;
ALTER DEFAULT PRIVILEGES IN SCHEMA kc GRANT ALL ON SEQUENCES TO keycloak;
