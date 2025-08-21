"""
Debug service to test managed identity in Azure Functions
"""
import os
import json
from typing import Dict
from datetime import datetime
from services.base import BaseProcessingService
from utils.logger import logger


class DebugManagedIdentityService(BaseProcessingService):
    """
    Service to debug managed identity token retrieval
    """
    
    def __init__(self):
        """Initialize debug service"""
        pass
    
    def get_supported_operations(self):
        """Return list of supported operations"""
        return ["debug_managed_identity"]
    
    def process(self, job_id: str, dataset_id: str, resource_id: str,
                version_id: str, operation_type: str) -> Dict:
        """Process debug operation"""
        
        results = {
            "environment": {},
            "tests": {}
        }
        
        # Check environment variables
        env_vars = [
            'IDENTITY_ENDPOINT', 'IDENTITY_HEADER', 
            'MSI_ENDPOINT', 'MSI_SECRET',
            'WEBSITE_INSTANCE_ID', 'FUNCTIONS_WORKER_RUNTIME',
            'POSTGIS_HOST', 'POSTGIS_DATABASE', 'POSTGIS_USER', 'POSTGIS_PASSWORD'
        ]
        
        for var in env_vars:
            value = os.environ.get(var, 'NOT SET')
            if 'PASSWORD' in var or 'SECRET' in var or 'HEADER' in var:
                results["environment"][var] = 'SET' if value != 'NOT SET' else 'NOT SET'
            else:
                results["environment"][var] = value
        
        # Test 1: DefaultAzureCredential
        try:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
            results["tests"]["DefaultAzureCredential"] = {
                "success": True,
                "token_length": len(token.token),
                "expires_on": datetime.fromtimestamp(token.expires_on).isoformat(),
                "token_preview": token.token[:20] + "..."
            }
        except Exception as e:
            results["tests"]["DefaultAzureCredential"] = {
                "success": False,
                "error": str(e)
            }
        
        # Test 2: ManagedIdentityCredential
        try:
            from azure.identity import ManagedIdentityCredential
            credential = ManagedIdentityCredential()
            token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
            results["tests"]["ManagedIdentityCredential"] = {
                "success": True,
                "token_length": len(token.token),
                "expires_on": datetime.fromtimestamp(token.expires_on).isoformat(),
                "token_preview": token.token[:20] + "..."
            }
        except Exception as e:
            results["tests"]["ManagedIdentityCredential"] = {
                "success": False,
                "error": str(e)
            }
        
        # Test 3: ManagedIdentityCredential with client_id
        try:
            from azure.identity import ManagedIdentityCredential
            credential = ManagedIdentityCredential(client_id="71e813b6-a83a-4e7e-99b7-9c5a9017da08")
            token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
            results["tests"]["ManagedIdentityCredential_with_client_id"] = {
                "success": True,
                "token_length": len(token.token),
                "expires_on": datetime.fromtimestamp(token.expires_on).isoformat(),
                "token_preview": token.token[:20] + "..."
            }
        except Exception as e:
            results["tests"]["ManagedIdentityCredential_with_client_id"] = {
                "success": False,
                "error": str(e)
            }
        
        # Test 4: Direct HTTP (Azure Functions specific)
        identity_endpoint = os.environ.get('IDENTITY_ENDPOINT')
        identity_header = os.environ.get('IDENTITY_HEADER')
        
        if identity_endpoint and identity_header:
            try:
                import urllib.request
                import urllib.parse
                
                resource = "https://ossrdbms-aad.database.windows.net/"
                url = f"{identity_endpoint}?resource={urllib.parse.quote(resource)}&api-version=2019-08-01"
                
                req = urllib.request.Request(url)
                req.add_header('X-IDENTITY-HEADER', identity_header)
                
                with urllib.request.urlopen(req) as response:
                    data = json.loads(response.read())
                    results["tests"]["Direct_HTTP"] = {
                        "success": True,
                        "token_length": len(data.get('access_token', '')),
                        "token_type": data.get('token_type', 'unknown'),
                        "token_preview": data.get('access_token', '')[:20] + "..."
                    }
            except Exception as e:
                results["tests"]["Direct_HTTP"] = {
                    "success": False,
                    "error": str(e)
                }
        else:
            results["tests"]["Direct_HTTP"] = {
                "success": False,
                "error": "IDENTITY_ENDPOINT or IDENTITY_HEADER not set"
            }
        
        # Test 5: PostgreSQL connection
        try:
            from azure.identity import ManagedIdentityCredential
            import psycopg
            
            credential = ManagedIdentityCredential()
            token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
            
            host = os.environ.get('POSTGIS_HOST', 'rmhpgflex.postgres.database.azure.com')
            database = os.environ.get('POSTGIS_DATABASE', 'geopgflex')
            
            conn_str = (
                f"host={host} "
                f"dbname={database} "
                f"user=rmhgeoapiqfn "
                f"password={token.token} "
                f"sslmode=require"
            )
            
            conn = psycopg.connect(conn_str)
            cur = conn.cursor()
            cur.execute("SELECT current_user, version()")
            result = cur.fetchone()
            conn.close()
            
            results["tests"]["PostgreSQL_Connection"] = {
                "success": True,
                "current_user": result[0],
                "version": str(result[1])[:50] + "..."
            }
        except Exception as e:
            results["tests"]["PostgreSQL_Connection"] = {
                "success": False,
                "error": str(e)
            }
        
        return {
            "status": "completed",
            "operation": "debug_managed_identity",
            "results": results
        }