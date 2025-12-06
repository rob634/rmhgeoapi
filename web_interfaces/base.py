"""
Web interfaces base module.

Abstract base class and common utilities for all web interface modules.

Exports:
    BaseInterface: Abstract base class with common HTML utilities and navigation
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
import azure.functions as func


class BaseInterface(ABC):
    """
    Abstract base class for all web interfaces.

    Provides:
        - Common CSS and JavaScript utilities
        - HTML document structure (wrap_html)
        - Navigation bar across all interfaces
        - Query parameter helpers

    Each interface must implement:
        - render(request) -> str
    """

    # Common CSS used by all interfaces
    # Design inspired by World Bank Data Catalog (https://datacatalog.worldbank.org)
    COMMON_CSS = """
        /* World Bank Color Variables */
        :root {
            --wb-blue-primary: #0071BC;
            --wb-blue-dark: #245AAD;
            --wb-navy: #053657;
            --wb-cyan: #00A3DA;
            --wb-gold: #FFC14D;
            --wb-gray: #626F86;
            --wb-gray-light: #e9ecef;
            --wb-bg: #f8f9fa;
        }

        /* CSS Reset */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: "Open Sans", Arial, sans-serif;
            background: var(--wb-bg);
            min-height: 100vh;
            padding: 20px;
            color: var(--wb-navy);
            font-size: 14px;
            line-height: 1.6;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        /* Common spinner */
        .spinner {
            border: 4px solid var(--wb-gray-light);
            border-top: 4px solid var(--wb-blue-primary);
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .hidden {
            display: none !important;
        }

        /* Status message */
        #status {
            padding: 12px 16px;
            border-radius: 3px;
            margin: 10px 0;
            font-size: 14px;
            border: 1px solid transparent;
        }

        #status.error {
            background: #fff5f5;
            border-color: #fc8181;
            color: #c53030;
        }

        #status.success {
            background: #f0fff4;
            border-color: #68d391;
            color: #2f855a;
        }
    """

    # Common JavaScript utilities
    COMMON_JS = """
        // API base URL (current origin)
        const API_BASE_URL = window.location.origin;

        // Show/hide spinner
        function showSpinner(id = 'spinner') {
            const el = document.getElementById(id);
            if (el) el.classList.remove('hidden');
        }

        function hideSpinner(id = 'spinner') {
            const el = document.getElementById(id);
            if (el) el.classList.add('hidden');
        }

        // Set status message
        function setStatus(msg, isError = false) {
            const el = document.getElementById('status');
            if (el) {
                el.textContent = msg;
                el.className = isError ? 'error' : 'success';
                el.style.display = 'block';
            }
        }

        // Clear status message
        function clearStatus() {
            const el = document.getElementById('status');
            if (el) el.style.display = 'none';
        }

        // Handle fetch errors consistently
        async function fetchJSON(url) {
            try {
                const response = await fetch(url);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                return await response.json();
            } catch (error) {
                console.error('Fetch error:', error);
                setStatus('Error: ' + error.message, true);
                throw error;
            }
        }
    """

    @abstractmethod
    def render(self, request: func.HttpRequest) -> str:
        """
        Generate HTML for this interface.

        This method MUST be implemented by each interface.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Complete HTML string (full document)
        """
        pass

    def get_query_params(self, request: func.HttpRequest) -> Dict[str, Any]:
        """
        Extract query parameters from request.

        Args:
            request: Azure Functions HttpRequest object

        Returns:
            Dictionary of query parameter key-value pairs

        Example:
            # Request: /api/interface/vector?collection=test&limit=100
            params = self.get_query_params(request)
            # params = {'collection': 'test', 'limit': '100'}
        """
        return {key: request.params.get(key) for key in request.params}

    def wrap_html(
        self,
        title: str,
        content: str,
        custom_css: str = "",
        custom_js: str = "",
        include_navbar: bool = True
    ) -> str:
        """
        Wrap content in complete HTML document.

        Includes:
            - Common CSS and custom CSS
            - Navigation bar (optional)
            - Content
            - Common JavaScript and custom JavaScript

        Args:
            title: Page title (appears in browser tab)
            content: HTML content for page body
            custom_css: Additional CSS specific to this interface
            custom_js: Additional JavaScript specific to this interface
            include_navbar: Whether to include navigation bar (default: True)

        Returns:
            Complete HTML document string

        Example:
            return self.wrap_html(
                title="STAC Dashboard",
                content="<h1>Hello World</h1>",
                custom_css=".my-class { color: red; }",
                custom_js="console.log('Hello');"
            )
        """
        navbar_html = self._render_navbar() if include_navbar else ""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        {self.COMMON_CSS}
        {custom_css}
    </style>
</head>
<body>
    {navbar_html}
    {content}
    <script>
        {self.COMMON_JS}
        {custom_js}
    </script>
</body>
</html>"""

    def _render_navbar(self) -> str:
        """
        Render navigation bar with links to all interfaces.

        Returns:
            HTML string for navigation bar

        Note:
            This is called automatically by wrap_html() unless
            include_navbar=False is specified.
        """
        return """
        <nav style="background: white; padding: 15px 30px; border-radius: 3px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px;
                    display: flex; justify-content: space-between; align-items: center;
                    border-bottom: 3px solid #0071BC;">
            <a href="/api/interface/home"
               style="font-size: 20px; font-weight: 700; color: #053657;
                      text-decoration: none; transition: color 0.2s;"
               onmouseover="this.style.color='#0071BC'"
               onmouseout="this.style.color='#053657'">
                🛰️ Geospatial API
            </a>
            <div style="display: flex; gap: 20px;">
                <a href="/api/interface/stac"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    STAC Collections
                </a>
                <a href="/api/interface/vector"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    OGC Features
                </a>
                <a href="/api/interface/pipeline"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    Pipeline
                </a>
                <a href="/api/interface/jobs"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    Job Monitor
                </a>
                <a href="/api/interface/docs"
                   style="color: #0071BC; text-decoration: none; font-weight: 600;
                          transition: color 0.2s;"
                   onmouseover="this.style.color='#00A3DA'"
                   onmouseout="this.style.color='#0071BC'">
                    API Docs
                </a>
            </div>
        </nav>
        """
