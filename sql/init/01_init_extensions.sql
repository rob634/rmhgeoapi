-- Initialize PostgreSQL extensions for RMH Geospatial ETL
-- This script runs automatically when Docker container starts

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS postgis_raster;
CREATE EXTENSION IF NOT EXISTS plpgsql;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create application schema
CREATE SCHEMA IF NOT EXISTS geo;

-- Set default search path
ALTER DATABASE rmhgeo SET search_path TO geo, public;

-- Create test user if needed (for local testing)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_user WHERE usename = 'rmhgeo_app') THEN
        CREATE USER rmhgeo_app WITH PASSWORD 'localtest123';
        GRANT ALL PRIVILEGES ON DATABASE rmhgeo TO rmhgeo_app;
        GRANT ALL ON SCHEMA geo TO rmhgeo_app;
        GRANT ALL ON SCHEMA public TO rmhgeo_app;
    END IF;
END
$$;

-- Verify extensions
SELECT extname, extversion FROM pg_extension ORDER BY extname;