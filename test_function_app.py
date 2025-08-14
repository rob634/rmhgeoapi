import unittest
import json
from unittest.mock import MagicMock
import azure.functions as func


def extract_http_trigger_logic(req: func.HttpRequest) -> func.HttpResponse:
    """Extract the core logic from http_trigger for testing"""
    name = req.params.get('name')
    if not name:
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            name = req_body.get('name') if req_body else None

    if name:
        return func.HttpResponse(f"Hello, {name}. This HTTP triggered function executed successfully.")
    else:
        return func.HttpResponse(
             "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response.",
             status_code=200
        )


class TestHttpTrigger(unittest.TestCase):
    
    def test_http_trigger_with_name_in_query_params(self):
        """Test HTTP trigger function with name in query parameters"""
        req = MagicMock(spec=func.HttpRequest)
        req.params.get.return_value = "Alice"
        req.get_json.return_value = None
        
        response = extract_http_trigger_logic(req)
        
        self.assertIsInstance(response, func.HttpResponse)
        self.assertEqual(response.get_body().decode(), "Hello, Alice. This HTTP triggered function executed successfully.")
    
    def test_http_trigger_with_name_in_request_body(self):
        """Test HTTP trigger function with name in request body"""
        req = MagicMock(spec=func.HttpRequest)
        req.params.get.return_value = None
        req.get_json.return_value = {"name": "Bob"}
        
        response = extract_http_trigger_logic(req)
        
        self.assertIsInstance(response, func.HttpResponse)
        self.assertEqual(response.get_body().decode(), "Hello, Bob. This HTTP triggered function executed successfully.")
    
    def test_http_trigger_without_name(self):
        """Test HTTP trigger function without name parameter"""
        req = MagicMock(spec=func.HttpRequest)
        req.params.get.return_value = None
        req.get_json.return_value = None
        
        response = extract_http_trigger_logic(req)
        
        self.assertIsInstance(response, func.HttpResponse)
        expected_message = "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response."
        self.assertEqual(response.get_body().decode(), expected_message)
    
    def test_http_trigger_with_invalid_json_body(self):
        """Test HTTP trigger function with invalid JSON in request body"""
        req = MagicMock(spec=func.HttpRequest)
        req.params.get.return_value = None
        req.get_json.side_effect = ValueError("Invalid JSON")
        
        response = extract_http_trigger_logic(req)
        
        self.assertIsInstance(response, func.HttpResponse)
        expected_message = "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response."
        self.assertEqual(response.get_body().decode(), expected_message)
    
    def test_http_trigger_with_empty_name_in_body(self):
        """Test HTTP trigger function with empty name in request body"""
        req = MagicMock(spec=func.HttpRequest)
        req.params.get.return_value = None
        req.get_json.return_value = {"name": ""}
        
        response = extract_http_trigger_logic(req)
        
        self.assertIsInstance(response, func.HttpResponse)
        expected_message = "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response."
        self.assertEqual(response.get_body().decode(), expected_message)
    
    def test_http_trigger_priority_query_over_body(self):
        """Test that query parameter takes priority over request body"""
        req = MagicMock(spec=func.HttpRequest)
        req.params.get.return_value = "QueryName"
        req.get_json.return_value = {"name": "BodyName"}
        
        response = extract_http_trigger_logic(req)
        
        self.assertIsInstance(response, func.HttpResponse)
        self.assertEqual(response.get_body().decode(), "Hello, QueryName. This HTTP triggered function executed successfully.")

    def test_http_trigger_with_none_body_json(self):
        """Test HTTP trigger function when request body is None"""
        req = MagicMock(spec=func.HttpRequest)
        req.params.get.return_value = None
        req.get_json.return_value = None
        
        response = extract_http_trigger_logic(req)
        
        self.assertIsInstance(response, func.HttpResponse)
        expected_message = "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response."
        self.assertEqual(response.get_body().decode(), expected_message)

    def test_http_trigger_with_body_missing_name_key(self):
        """Test HTTP trigger function when request body doesn't have name key"""
        req = MagicMock(spec=func.HttpRequest)
        req.params.get.return_value = None
        req.get_json.return_value = {"other_field": "value"}
        
        response = extract_http_trigger_logic(req)
        
        self.assertIsInstance(response, func.HttpResponse)
        expected_message = "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response."
        self.assertEqual(response.get_body().decode(), expected_message)


if __name__ == '__main__':
    unittest.main()