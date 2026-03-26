"""Tests for infrastructure.auth.rbac module."""

import base64
import json
import pytest
from unittest.mock import MagicMock, patch


class TestGetCallerIdentity:
    """Test get_caller_identity() header extraction."""

    def test_returns_anonymous_when_no_headers(self):
        """No Easy Auth headers -> anonymous identity."""
        from infrastructure.auth.rbac import get_caller_identity
        req = MagicMock()
        req.headers = {}

        identity = get_caller_identity(req)

        assert identity.is_anonymous is True
        assert identity.name is None
        assert identity.roles == []

    def test_extracts_identity_from_easy_auth_headers(self):
        """Easy Auth headers present -> populated identity."""
        from infrastructure.auth.rbac import get_caller_identity

        claims = {
            "claims": [
                {"typ": "name", "val": "Robert Harrison"},
                {"typ": "roles", "val": "GeoAdmin"},
                {"typ": "preferred_username", "val": "rharrison1@worldbankgroup.org"},
            ]
        }
        principal_b64 = base64.b64encode(json.dumps(claims).encode()).decode()

        req = MagicMock()
        req.headers = {
            'X-MS-CLIENT-PRINCIPAL-NAME': 'Robert Harrison',
            'X-MS-CLIENT-PRINCIPAL-ID': 'abc-123',
            'X-MS-CLIENT-PRINCIPAL-IDP': 'aad',
            'X-MS-CLIENT-PRINCIPAL': principal_b64,
        }

        identity = get_caller_identity(req)

        assert identity.is_anonymous is False
        assert identity.name == 'Robert Harrison'
        assert identity.principal_id == 'abc-123'
        assert 'GeoAdmin' in identity.roles
        assert identity.email == 'rharrison1@worldbankgroup.org'

    def test_handles_malformed_principal_blob(self):
        """Bad base64 blob -> falls back to header-only identity."""
        from infrastructure.auth.rbac import get_caller_identity
        req = MagicMock()
        req.headers = {
            'X-MS-CLIENT-PRINCIPAL-NAME': 'Test User',
            'X-MS-CLIENT-PRINCIPAL-ID': 'xyz-789',
            'X-MS-CLIENT-PRINCIPAL': 'not-valid-base64!!!',
        }

        identity = get_caller_identity(req)

        assert identity.is_anonymous is False
        assert identity.name == 'Test User'
        assert identity.roles == []  # Could not parse roles from blob


class TestRequireRole:
    """Test @require_role() decorator."""

    @patch('infrastructure.auth.rbac._get_auth_config')
    def test_passes_through_when_gates_disabled(self, mock_config):
        """AUTH_GATES_ENABLED=false -> decorator is no-op."""
        from infrastructure.auth.rbac import require_role
        mock_config.return_value = MagicMock(gates_enabled=False)

        @require_role('GeoAdmin')
        def handler(req):
            return 'ok'

        req = MagicMock()
        req.headers = {}  # No auth headers
        result = handler(req)
        assert result == 'ok'

    @patch('infrastructure.auth.rbac._get_auth_config')
    def test_returns_403_when_role_missing(self, mock_config):
        """Gates enabled + role missing -> 403. Response must NOT leak role names."""
        from infrastructure.auth.rbac import require_role
        mock_config.return_value = MagicMock(gates_enabled=True)

        @require_role('GeoAdmin')
        def handler(req):
            return 'ok'

        req = MagicMock()
        req.headers = {
            'X-MS-CLIENT-PRINCIPAL-NAME': 'No-Role User',
            'X-MS-CLIENT-PRINCIPAL-ID': 'abc',
        }
        result = handler(req)
        assert result.status_code == 403
        # Must not contain role names (information disclosure)
        body = result.get_body().decode() if hasattr(result, 'get_body') else str(result)
        assert 'GeoAdmin' not in body

    @patch('infrastructure.auth.rbac._get_auth_config')
    def test_passes_when_role_present(self, mock_config):
        """Gates enabled + role present -> passes through."""
        from infrastructure.auth.rbac import require_role
        mock_config.return_value = MagicMock(gates_enabled=True)

        claims = {
            "claims": [
                {"typ": "roles", "val": "GeoAdmin"},
            ]
        }
        principal_b64 = base64.b64encode(json.dumps(claims).encode()).decode()

        @require_role('GeoAdmin')
        def handler(req):
            return 'ok'

        req = MagicMock()
        req.headers = {
            'X-MS-CLIENT-PRINCIPAL-NAME': 'Admin User',
            'X-MS-CLIENT-PRINCIPAL-ID': 'abc',
            'X-MS-CLIENT-PRINCIPAL': principal_b64,
        }
        result = handler(req)
        assert result == 'ok'

    @patch('infrastructure.auth.rbac._get_auth_config')
    def test_returns_401_when_anonymous_and_gates_enabled(self, mock_config):
        """Gates enabled + no identity -> 401."""
        from infrastructure.auth.rbac import require_role
        mock_config.return_value = MagicMock(gates_enabled=True)

        @require_role('GeoAdmin')
        def handler(req):
            return 'ok'

        req = MagicMock()
        req.headers = {}
        result = handler(req)
        assert result.status_code == 401

    @patch('infrastructure.auth.rbac._get_auth_config')
    def test_multi_role_any_match_passes(self, mock_config):
        """Gates enabled + caller has one of multiple allowed roles -> passes."""
        from infrastructure.auth.rbac import require_role
        mock_config.return_value = MagicMock(gates_enabled=True)

        claims = {
            "claims": [
                {"typ": "roles", "val": "DataManager"},
            ]
        }
        principal_b64 = base64.b64encode(json.dumps(claims).encode()).decode()

        @require_role('GeoAdmin', 'DataManager')
        def handler(req):
            return 'ok'

        req = MagicMock()
        req.headers = {
            'X-MS-CLIENT-PRINCIPAL-NAME': 'Data User',
            'X-MS-CLIENT-PRINCIPAL-ID': 'abc',
            'X-MS-CLIENT-PRINCIPAL': principal_b64,
        }
        result = handler(req)
        assert result == 'ok'
