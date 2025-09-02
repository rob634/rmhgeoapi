#!/usr/bin/env python3
"""
Schema Deployment Script - PostgreSQL Table Creation

Simple script to deploy the database schema by executing the SQL definition
against the configured PostgreSQL database. Reads environment variables
for database connection and creates tables if they don't exist.

Usage:
    python deploy_schema.py

Environment Variables Required:
    POSTGIS_HOST, POSTGIS_USER, POSTGIS_PASSWORD, POSTGIS_DATABASE, APP_SCHEMA
"""

import os
import sys
from pathlib import Path

from util_logger import LoggerFactory, ComponentType

# Set up logging using LoggerFactory
logger = LoggerFactory.get_logger(ComponentType.UTIL, "SchemaDeployer")


def main():
    """Deploy PostgreSQL schema using environment variables."""
    
    # Validate required environment variables
    required_vars = [
        'POSTGIS_HOST', 'POSTGIS_USER', 'POSTGIS_PASSWORD', 
        'POSTGIS_DATABASE'
    ]
    
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        logger.error(f"❌ Missing required environment variables: {missing_vars}")
        sys.exit(1)
    
    # Get configuration
    host = os.environ['POSTGIS_HOST']
    user = os.environ['POSTGIS_USER']
    password = os.environ['POSTGIS_PASSWORD']
    database = os.environ['POSTGIS_DATABASE']
    app_schema = os.environ.get('APP_SCHEMA', 'app')
    
    logger.info(f"🐘 Deploying schema to {host}:{database} schema: {app_schema}")
    
    # Read schema SQL file
    schema_file = Path(__file__).parent / 'schema_postgres.sql'
    if not schema_file.exists():
        logger.error(f"❌ Schema file not found: {schema_file}")
        sys.exit(1)
    
    try:
        import psycopg
        
        # Connection string
        conn_str = f"host={host} dbname={database} user={user} password={password}"
        
        with psycopg.connect(conn_str) as conn:
            with conn.cursor() as cursor:
                # Read and execute schema SQL
                schema_sql = schema_file.read_text()
                
                # Replace schema placeholders
                schema_sql = schema_sql.replace('CREATE SCHEMA IF NOT EXISTS app;', f'CREATE SCHEMA IF NOT EXISTS {app_schema};')
                schema_sql = schema_sql.replace('SET search_path TO app, public;', f'SET search_path TO {app_schema}, public;')
                
                logger.info("📋 Executing schema SQL...")
                cursor.execute(schema_sql)
                conn.commit()
                
                # Verify tables were created
                cursor.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = %s AND table_name IN ('jobs', 'tasks')
                """, (app_schema,))
                
                created_tables = [row[0] for row in cursor.fetchall()]
                
                if len(created_tables) == 2:
                    logger.info(f"✅ Schema deployment successful! Created tables: {created_tables}")
                else:
                    logger.warning(f"⚠️ Partial deployment. Tables found: {created_tables}")
                
    except Exception as e:
        logger.error(f"❌ Schema deployment failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()