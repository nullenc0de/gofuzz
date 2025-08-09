#!/usr/bin/env python3

import asyncio
import aiohttp
import sys
import tempfile
import os
import json
import argparse
import logging
import shutil
from typing import Dict, List, Any, Optional
from urllib.parse import urljoin, urlparse

class GoFuzz:
    def __init__(self, silent: bool = False):
        self.session = None
        self.silent = silent
        
        # Check if jsluice is available
        self.jsluice_available = shutil.which('jsluice') is not None
        if not self.jsluice_available and not silent:
            logging.warning("jsluice not found. Install with: go install github.com/BishopFox/jsluice/cmd/jsluice@latest")
        
        # Configure logging
        if silent:
            level = logging.CRITICAL
        else:
            level = logging.WARNING
            
        logging.basicConfig(
            level=level,
            format='%(levelname)s: %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(limit=10, limit_per_host=3, ssl=False)
        timeout = aiohttp.ClientTimeout(total=10, connect=3)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _is_interesting_url(self, url: str) -> bool:
        """Filter out uninteresting URLs"""
        if not url or len(url) < 5:
            return False
            
        boring_patterns = [
            'http://www.w3.org/',
            'https://www.w3.org/',
            'xmlns',
            'javascript:',
            'data:image/',
            'data:text/',
            '#',
            'mailto:',
            'telerik.com',
            'kendo-',
        ]
        
        url_lower = url.lower()
        if any(pattern in url_lower for pattern in boring_patterns):
            return False
            
        if len(url) <= 10 and not url.startswith(('http', '/')):
            return False
            
        return True

    def _is_likely_js_url(self, url: str) -> bool:
        """Check if URL is likely a JavaScript file"""
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        if any(path.endswith(ext) for ext in ['.js', '.mjs', '.es6', '.es']):
            return True
            
        js_patterns = [
            '/js/', '/javascript/', '/assets/js/', '/static/js/',
            '/bundles/', '/chunks/', '/webpack/', '/dist/',
            'jquery', 'bootstrap', 'react', 'vue', 'angular',
            'app.', 'main.', 'bundle.', 'chunk.', 'vendor.',
            'min.js', 'prod.js'
        ]
        
        if any(pattern in path for pattern in js_patterns):
            return True
            
        # API endpoints should not be treated as JS files
        api_patterns = [
            '/api/', '/v1/', '/v2/', '/v3/', '/rest/', '/graphql',
            '.json', '.xml', '/users/', '/notifications/'
        ]
        
        if any(pattern in path for pattern in api_patterns):
            return False
                
        return False

    async def fetch_url(self, url: str) -> Optional[str]:
        """Fetch URL content with error handling"""
        try:
            # Skip image files
            if any(url.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp']):
                return None
                
            async with self.session.get(url) as response:
                if response.status == 200:
                    content = await response.text()
                    return content
                else:
                    if not self.silent and response.status not in [403, 404, 500]:
                        self.logger.warning(f"Failed to fetch {url}: HTTP {response.status}")
                    return None
        except UnicodeDecodeError:
            return None
        except Exception as e:
            if not self.silent and not isinstance(e, (asyncio.TimeoutError, aiohttp.ClientSSLError)):
                self.logger.error(f"Error fetching {url}: {e}")
            return None

    async def run_jsluice_command(self, command: List[str]) -> List[str]:
        """Run a jsluice command with timeout"""
        if not self.jsluice_available:
            return []
            
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return []
            
            if process.returncode != 0:
                return []
                
            lines = stdout.decode().strip().split('\n') if stdout.decode().strip() else []
            return lines
            
        except Exception as e:
            return []

    def extract_urls_regex_fallback(self, content: str, base_url: str) -> List[str]:
        """Fallback regex extraction when jsluice is not available"""
        import re
        urls = set()
        
        url_patterns = [
            r'["\']((https?://[^\s"\'<>]+))["\']',
            r'["\']((\/[a-zA-Z0-9\/._-]{5,}))["\']',
            r'["\']((wss?://[^\s"\'<>]+))["\']',
        ]
        
        for pattern in url_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    found_url = match[0] if match[0] else match[1]
                else:
                    found_url = match
                
                if self._is_interesting_url(found_url):
                    # Resolve relative URLs
                    if found_url.startswith('/'):
                        # Relative path - resolve against base URL
                        parsed_base = urlparse(base_url)
                        resolved_url = f"{parsed_base.scheme}://{parsed_base.netloc}{found_url}"
                        urls.add(resolved_url)
                    elif found_url.startswith(('http://', 'https://', 'ws://', 'wss://')):
                        # Already absolute
                        urls.add(found_url)
                    else:
                        # Relative path without leading slash
                        resolved_url = urljoin(base_url, found_url)
                        urls.add(resolved_url)
        
        return list(urls)

    def extract_secrets_regex_fallback(self, content: str) -> List[str]:
        """Fallback regex secret extraction when jsluice is not available"""
        import re
        secrets = set()
        
        secret_patterns = [
            r'["\']([A-Za-z0-9+/]{40,}={0,2})["\']',  # Base64-like strings
            r'["\']([A-Fa-f0-9]{32,})["\']',          # Hex strings
            r'(sk_[a-zA-Z0-9]{20,})',                 # Stripe secret keys
            r'(pk_[a-zA-Z0-9]{20,})',                 # Stripe public keys
            r'(AKIA[0-9A-Z]{16})',                    # AWS access keys
        ]
        
        for pattern in secret_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                if isinstance(match, str) and len(match) > 20:
                    if not any(boring in match.lower() for boring in ['test', 'example', 'demo']):
                        secrets.add(match)
        
        return list(secrets)

    async def process_js_file(self, url: str, content: str) -> Dict[str, Any]:
        """Process a JavaScript file and extract information"""
        results = {
            'js_urls': [],
            'other_urls': [],
            'secrets': []
        }
        
        # Write content to temp file for jsluice
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
            f.write(content)
            temp_file = f.name
        
        try:
            if self.jsluice_available:
                # Use jsluice for superior analysis with path resolution
                # Extract URLs and resolve relative paths
                urls_cmd = ['jsluice', 'urls', '-R', url, temp_file]
                url_lines = await self.run_jsluice_command(urls_cmd)
                
                for line in url_lines:
                    line = line.strip()
                    if line:
                        try:
                            if line.startswith('{'):
                                data = json.loads(line)
                                extracted_url = data.get('url', '')
                                if extracted_url and self._is_interesting_url(extracted_url):
                                    if self._is_likely_js_url(extracted_url):
                                        results['js_urls'].append(extracted_url)
                                    else:
                                        results['other_urls'].append(extracted_url)
                        except (json.JSONDecodeError, KeyError):
                            if self._is_interesting_url(line):
                                if self._is_likely_js_url(line):
                                    results['js_urls'].append(line)
                                else:
                                    results['other_urls'].append(line)
                
                # Extract secrets
                secrets_cmd = ['jsluice', 'secrets', temp_file]
                secret_lines = await self.run_jsluice_command(secrets_cmd)
                for line in secret_lines:
                    line = line.strip()
                    if line:
                        try:
                            if line.startswith('{'):
                                data = json.loads(line)
                                # Extract different types of secret data
                                secret_data = data.get('data', {})
                                if isinstance(secret_data, dict):
                                    for key, value in secret_data.items():
                                        if isinstance(value, str) and len(value) > 10:
                                            results['secrets'].append(f"{key}: {value}")
                                elif isinstance(secret_data, str):
                                    results['secrets'].append(secret_data)
                        except json.JSONDecodeError:
                            results['secrets'].append(line)
            else:
                # Fallback to regex extraction with path resolution
                urls = self.extract_urls_regex_fallback(content, url)
                for extracted_url in urls:
                    if self._is_likely_js_url(extracted_url):
                        results['js_urls'].append(extracted_url)
                    else:
                        results['other_urls'].append(extracted_url)
                
                secrets = self.extract_secrets_regex_fallback(content)
                results['secrets'] = secrets
            
        finally:
            try:
                os.unlink(temp_file)
            except:
                pass
        
        return results

    async def process_url(self, url: str) -> Dict[str, Any]:
        """Process a URL"""
        if not self.silent:
            self.logger.info(f"Processing: {url}")
        
        content = await self.fetch_url(url)
        if not content:
            return {}
        
        results = await self.process_js_file(url, content)
        return results

    def print_results(self, results: Dict[str, Any], urls_only: bool = False, secrets_only: bool = False, show_secrets: bool = False):
        """Print results based on user preferences"""
        # Remove duplicates
        unique_js_urls = list(dict.fromkeys(results.get('js_urls', [])))
        unique_other_urls = list(dict.fromkeys(results.get('other_urls', [])))
        unique_secrets = list(dict.fromkeys(results.get('secrets', [])))
        
        if self.silent:
            # Silent mode: output based on flags
            if secrets_only:
                for secret in unique_secrets:
                    print(secret)
            elif urls_only or not show_secrets:
                # Default: URLs only
                for js_url in unique_js_urls:
                    print(js_url)
                for other_url in unique_other_urls:
                    print(other_url)
            else:
                # Both URLs and secrets
                for js_url in unique_js_urls:
                    print(js_url)
                for other_url in unique_other_urls:
                    print(other_url)
                for secret in unique_secrets:
                    print(secret)
        else:
            # Normal mode: formatted output
            total_js = len(unique_js_urls)
            total_other = len(unique_other_urls)
            total_secrets = len(unique_secrets)
            
            if secrets_only:
                if total_secrets > 0:
                    self.logger.info(f"Found: {total_secrets} secrets")
                for secret in unique_secrets:
                    print(f"SECRET: {secret}")
            elif urls_only or not show_secrets:
                # Default: URLs only
                if total_js + total_other > 0:
                    self.logger.info(f"Found: {total_js} JS URLs, {total_other} other URLs")
                for js_url in unique_js_urls:
                    print(f"JS: {js_url}")
                for other_url in unique_other_urls:
                    print(f"URL: {other_url}")
            else:
                # Both URLs and secrets
                if total_js + total_other + total_secrets > 0:
                    self.logger.info(f"Found: {total_js} JS URLs, {total_other} other URLs, {total_secrets} secrets")
                for js_url in unique_js_urls:
                    print(f"JS: {js_url}")
                for other_url in unique_other_urls:
                    print(f"URL: {other_url}")
                for secret in unique_secrets:
                    print(f"SECRET: {secret}")

async def main():
    parser = argparse.ArgumentParser(description='GoFuzz - JavaScript security analysis tool (with jsluice integration)')
    parser.add_argument('--silent', action='store_true', help='Silent mode - output only URLs/secrets')
    parser.add_argument('--urls-only', action='store_true', help='Output only URLs (no secrets)')
    parser.add_argument('--secrets-only', action='store_true', help='Output only secrets (no URLs)')
    parser.add_argument('--show-secrets', action='store_true', help='Include secrets in output (default: URLs only)')
    
    args = parser.parse_args()
    
    # Read URLs from stdin
    urls = []
    for line in sys.stdin:
        url = line.strip()
        if url:
            urls.append(url)
    
    if not urls:
        print("No URLs provided via stdin", file=sys.stderr)
        return
    
    async with GoFuzz(silent=args.silent) as gofuzz:
        for url in urls:
            try:
                results = await gofuzz.process_url(url)
                gofuzz.print_results(
                    results, 
                    urls_only=args.urls_only,
                    secrets_only=args.secrets_only,
                    show_secrets=args.show_secrets
                )
            except Exception as e:
                if not args.silent:
                    gofuzz.logger.error(f"Error processing {url}: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 
