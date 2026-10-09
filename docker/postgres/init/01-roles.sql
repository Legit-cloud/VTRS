-- Development database roles (spec section 6.2). Runs once, on first container start.
--   vtrs_migrator  owns the schema and runs migrations (DDL)
--   vtrs_app       the running application (DML only; immutable tables lose UPDATE/DELETE in migrations)
--   vtrs_readonly  reporting and replicas
-- Passwords are local development placeholders.
CREATE ROLE vtrs_migrator LOGIN PASSWORD 'vtrs_migrator_dev';
CREATE ROLE vtrs_app LOGIN PASSWORD 'vtrs_app_dev';
CREATE ROLE vtrs_readonly LOGIN PASSWORD 'vtrs_readonly_dev';

CREATE DATABASE vtrs OWNER vtrs_migrator;

\connect vtrs

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO vtrs_app, vtrs_readonly;

ALTER DEFAULT PRIVILEGES FOR ROLE vtrs_migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO vtrs_app;
ALTER DEFAULT PRIVILEGES FOR ROLE vtrs_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO vtrs_app;
ALTER DEFAULT PRIVILEGES FOR ROLE vtrs_migrator IN SCHEMA public
    GRANT SELECT ON TABLES TO vtrs_readonly;
