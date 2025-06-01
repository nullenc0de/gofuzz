#!/usr/bin/env python3

import asyncio
import subprocess
import tempfile
import os
import json
import re
import logging
import argparse
import sys
from typing import Dict, List, Any, Set, Optional
from urllib.parse import urljoin, urlparse
import aiohttp
import string

class JSluiceWrapper:
    def __init__(self, debug_queries: bool = False):
        self.logger = logging.getLogger(__name__)
        self.debug_queries = debug_queries
        
    async def run_jsluice_command(self, command: List[str]) -> List[str]:
        """Run a jsluice command and return the output lines"""
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                self.logger.error(f"jsluice command failed: {' '.join(command)}")
                self.logger.error(f"stderr: {stderr.decode()}")
                return []
                
            lines = stdout.decode().strip().split('\n') if stdout.decode().strip() else []
            if self.debug_queries:
                self.logger.debug(f"JSluice returned {len(lines)} lines for {command[-1] if command else 'unknown'}")
            return lines
            
        except Exception as e:
            self.logger.error(f"Error running jsluice command: {e}")
            return []

    async def run_api_queries(self, url: str, content: str) -> List[Dict[str, Any]]:
        """Run tree-sitter queries to find reconstructable API calls and endpoints"""
        
        # Quick pre-filter: skip files that are unlikely to have APIs
        if len(content) < 1000:  # Very small files unlikely to have meaningful APIs
            if self.debug_queries:
                self.logger.debug(f"Skipping small file ({len(content)} chars): {url}")
            return []
        
        # Skip overly minified files that are clearly just garbage
        if len(content) > 100000:  # Large files
            # Check ratio of meaningful characters to total
            printable_chars = sum(1 for c in content[:10000] if c in string.printable)
            if printable_chars / min(len(content), 10000) < 0.7:
                if self.debug_queries:
                    self.logger.debug(f"Skipping heavily minified/binary content: {url}")
                return []
        
        # More aggressive content pre-filtering for minified code
        content_lower = content.lower()
        
        # Check for actual fetch/axios/xhr patterns, not just keywords
        real_api_patterns = [
            r'fetch\s*\(\s*["\'][^"\']{10,}["\']',     # fetch with substantial URL
            r'axios\.[a-zA-Z]+\s*\(\s*["\'][^"\']{10,}["\']',  # axios with substantial URL
            r'\.open\s*\(\s*["\'][^"\']+["\'],\s*["\'][^"\']{10,}["\']',  # XHR open with URL
            r'new\s+WebSocket\s*\(\s*["\'][^"\']{10,}["\']',   # WebSocket with substantial URL
            r'["\']https?://[a-zA-Z0-9.-]{5,}[/][^"\']{3,}["\']',  # Full HTTP URLs
            r'["\'][^"\']*\/api\/[^"\']{5,}["\']',     # API paths
            r'["\'][^"\']*\/v\d+\/[^"\']{5,}["\']',    # Versioned APIs
        ]
        
        has_real_api_patterns = any(re.search(pattern, content) for pattern in real_api_patterns)
        
        if not has_real_api_patterns:
            if self.debug_queries:
                self.logger.debug(f"No realistic API patterns found in content, skipping tree-sitter queries: {url}")
            return []
        
        if self.debug_queries:
            self.logger.debug(f"Found realistic API patterns, proceeding with tree-sitter queries: {url}")
        
        # Much more restrictive queries that should only match real API calls
        api_queries = [
            # Only fetch calls with substantial URLs (10+ characters)
            '(call_expression function: (identifier) @func arguments: (arguments (string) @url)) (#eq? @func "fetch") (#match? @url "^.{10,}$")',
            
            # Only method fetch calls with substantial URLs
            '(call_expression function: (member_expression property: (property_identifier) @method) arguments: (arguments (string) @url)) (#eq? @method "fetch") (#match? @url "^.{10,}$")',
            
            # Only XHR calls with real URLs
            '(call_expression function: (member_expression property: (property_identifier) @method) arguments: (arguments (string) @http_method (string) @url)) (#eq? @method "open") (#match? @url "^.{10,}$")',
            
            # Only axios calls with substantial URLs
            '(call_expression function: (member_expression object: (identifier) @obj property: (property_identifier) @method) arguments: (arguments (string) @url)) (#match? @obj "axios") (#match? @url "^.{10,}$")',
            
            # Only WebSocket with substantial URLs
            '(new_expression constructor: (identifier) @constructor arguments: (arguments (string) @url)) (#eq? @constructor "WebSocket") (#match? @url "^.{10,}$")',
            
            # Only strings that look like real API endpoints (very restrictive)
            '(string) @api_string (#match? @api_string "^(https?://[a-zA-Z0-9.-]{5,}/[a-zA-Z0-9/._-]{5,}|/api/[a-zA-Z0-9/._-]{5,}|/v[0-9]+/[a-zA-Z0-9/._-]{5,}|[a-zA-Z0-9.-]{5,}/graphql|localhost:[0-9]+/[a-zA-Z0-9/._-]{3,}|127\\.0\\.0\\.1:[0-9]+/[a-zA-Z0-9/._-]{3,})$")',
        ]
        
        all_patterns = []
        
        # Write content to temporary file for jsluice
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
            f.write(content)
            temp_file = f.name
        
        try:
            # Run each query
            for i, query in enumerate(api_queries, 1):
                if self.debug_queries:
                    self.logger.debug(f"Running query {i}/{len(api_queries)}")
                    
                cmd = ['jsluice', 'query', '-q', query, '-f', temp_file]
                lines = await self.run_jsluice_command(cmd)
                
                if self.debug_queries:
                    self.logger.debug(f"Query {i} returned {len(lines)} results")
                
                # Parse the results
                for line in lines:
                    if line.strip():
                        try:
                            data = json.loads(line)
                            data['query_type'] = f'query_{i}'
                            data['filename'] = temp_file
                            data['original_file'] = url
                            all_patterns.append(data)
                        except json.JSONDecodeError:
                            continue
                            
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_file)
            except:
                pass
        
        # Filter to only interesting patterns
        found_patterns = [p for p in all_patterns if self._is_potentially_interesting(p)]
        
        # Only show summary if we found something or if explicitly debugging
        if found_patterns:
            if self.debug_queries:
                self.logger.debug(f"Found {len(found_patterns)} meaningful API patterns")
        elif self.debug_queries:
            self.logger.debug(f"No meaningful API patterns found in {url}")
                
        return found_patterns

    def _is_potentially_interesting(self, data: Dict[str, Any]) -> bool:
        """Enhanced filtering - only include actual API patterns"""
        data_str = json.dumps(data).lower()
        
        # First, check if we have any actual URL data
        url_value = data.get('url', '')
        api_string_value = data.get('api_string', '')
        raw_value = data.get('raw_value', '')
        
        # Check all possible URL fields
        all_url_values = [url_value, api_string_value, raw_value]
        valid_url_found = False
        
        for value in all_url_values:
            if value and value not in ['undefined', 'null', '', 'false', 'true']:
                # Check minimum length
                if len(str(value).strip()) >= 10:  # Increased minimum length
                    # Check if it looks like a real URL/endpoint
                    if self._is_valid_url_string(str(value)):
                        valid_url_found = True
                        break
        
        if not valid_url_found:
            # Don't log rejections for obviously invalid patterns to reduce noise
            return False
        
        # Skip obvious DOM manipulation and UI code
        dom_junk = [
            'queryselector', 'getelementby', 'addeventlistener', 'removeeventlistener',
            'mouseenter', 'mouseleave', 'mouseout', 'mouseover', 'click', 'focus', 'blur',
            'innerhtml', 'innertext', 'textcontent', 'classlist', 'setattribute', 'getattribute',
            'style.', '.style', 'classname', 'px', 'em', 'rem', '%', 'rgba', 'rgb', '#fff', '#000',
            'data-', 'js-', 'cmp-', '.slider', '.button', '.nav', '.menu', '.banner', 'entries'
        ]
        
        if any(junk in data_str for junk in dom_junk):
            return False
        
        # Check for minified/obfuscated function names (single/double letters)
        func_name = data.get('func', '')
        if func_name and len(func_name) <= 2 and func_name.isalpha():
            return False
        
        # Only include patterns that are clearly API-related
        api_indicators = [
            # Function names
            'fetch', 'axios', 'ajax', 'xmlhttprequest', 'websocket',
            # URL patterns (but not XML namespaces)
            'localhost:', '127.0.0.1',
            '/api/', '/v1/', '/v2/', '/v3/', '/graphql', '/rest',
            # Data formats
            'application/json', 'application/xml', 'json', 'xml',
            # HTTP methods
            '"get"', '"post"', '"put"', '"delete"', '"patch"',
            # API-specific terms
            'endpoint', 'baseurl', 'apiurl', 'apiendpoint',
            # Account/user URLs
            'myaccount.', '/accountcenter/', '/users/', '/notifications/'
        ]
        
        has_api_indicator = any(indicator in data_str for indicator in api_indicators)
        
        # Specifically exclude XML namespace URLs even if they match other patterns
        if 'www.w3.org' in data_str:
            return False
            
        if not has_api_indicator:
            return False
            
        return True

    def _is_valid_url_string(self, value: str) -> bool:
        """Check if a string looks like a valid URL or API endpoint"""
        if not value or len(value) < 10:  # Increased minimum length
            return False
            
        # Skip obvious non-URLs
        invalid_values = ['undefined', 'null', 'true', 'false', '', 'this', 'self', 'window', 'document',
                         'function', 'return', 'var', 'let', 'const', 'if', 'else', 'for', 'while',
                         'switch', 'case', 'break', 'continue', 'typeof', 'instanceof', 'new', 'delete']
        if value.lower() in invalid_values:
            return False
            
        # Skip strings that are just numbers, single letters, or very short identifiers
        if value.isdigit() or (value.isalnum() and len(value) <= 6):
            return False
            
        # Skip obvious JavaScript code patterns
        js_code_patterns = [
            r'^[a-zA-Z]\w{0,2}$',      # Short variable names like 'x', 'ab', 'foo'
            r'^[A-Z]{1,3}$',           # Short constants like 'A', 'AB', 'ABC'
            r'^[a-z]{1,3}$',           # Short variables like 'a', 'ab', 'abc'
            r'^[0-9a-fA-F]{1,8}$',     # Short hex values
            r'^[a-zA-Z]{1,4}\d{0,2}$'  # Short mixed like 'a1', 'foo2'
        ]
        
        if any(re.match(pattern, value) for pattern in js_code_patterns):
            return False
            
        # Check for URL-like patterns (more restrictive)
        url_patterns = [
            r'^https?://[a-zA-Z0-9.-]{3,}/.{3,}',     # Full URLs with path
            r'^/api/[a-zA-Z0-9/._-]{5,}',             # API paths with substance
            r'^/v\d+/[a-zA-Z0-9/._-]{5,}',           # Versioned APIs with substance
            r'localhost:\d+/.{3,}',                  # Local development with path
            r'127\.0\.0\.1:\d+/.{3,}',               # Local IP with path
            r'[a-zA-Z0-9.-]{3,}/graphql',            # GraphQL endpoints
            r'^wss?://[a-zA-Z0-9.-]{3,}/.{3,}',      # WebSocket URLs with path
        ]
        
        return any(re.search(pattern, value, re.IGNORECASE) for pattern in url_patterns)

    def _find_api_patterns_regex(self, content: str, url: str) -> List[Dict[str, Any]]:
        """Fallback regex-based API pattern detection"""
        patterns = []
        
        # Only look for very obvious API patterns as fallback
        api_regex_patterns = [
            (r'fetch\s*\(\s*["\']([^"\']{10,})["\']', 'fetch_call'),
            (r'axios\.(?:get|post|put|delete|patch)\s*\(\s*["\']([^"\']{10,})["\']', 'axios_call'),
            (r'new\s+WebSocket\s*\(\s*["\']([^"\']{10,})["\']', 'websocket_call'),
        ]
        
        for pattern, call_type in api_regex_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                url_value = match.group(1)
                if self._is_valid_url_string(url_value):
                    patterns.append({
                        'type': call_type,
                        'url': url_value,
                        'original_file': url,
                        'query_type': 'regex_fallback'
                    })
        
        return patterns

class GoFuzz:
    def __init__(self, debug: bool = False, debug_queries: bool = False, silent: bool = False):
        self.session = None
        self.jsluice = JSluiceWrapper(debug_queries=debug_queries)
        self.debug = debug
        self.debug_queries = debug_queries
        self.silent = silent
        
        # Configure logging
        if silent:
            level = logging.ERROR  # Only show errors in silent mode
        elif debug:
            level = logging.DEBUG
        else:
            level = logging.INFO
            
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    async def __aenter__(self):
        connector = aiohttp.TCPConnector(limit=50, limit_per_host=10)
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
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
        """Filter out uninteresting URLs like XML namespaces"""
        if not url or len(url) < 5:
            return False
            
        # Skip XML namespaces and other noise
        boring_patterns = [
            'http://www.w3.org/',           # XML namespaces
            'https://www.w3.org/',          # XML namespaces (HTTPS)
            'xmlns',                        # XML namespace declarations
            'javascript:',                  # JavaScript pseudo-URLs
            'data:image/',                  # Data URLs for images
            'data:text/',                   # Data URLs for text
            '#',                           # Fragment-only URLs
            'mailto:',                     # Email links
            'EXPREXPREXPR',                # Placeholder/template expressions
        ]
        
        url_lower = url.lower()
        if any(pattern in url_lower for pattern in boring_patterns):
            return False
            
        # Skip very short or obviously invalid URLs
        if len(url) <= 10 and not url.startswith(('http', '/')):
            return False
            
        return True

    def _is_likely_js_url(self, url: str) -> bool:
        """Enhanced JS URL detection"""
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        # Common JS file extensions
        if any(path.endswith(ext) for ext in ['.js', '.mjs', '.es6', '.es']):
            return True
            
        # Common JS paths/patterns
        js_patterns = [
            '/js/', '/javascript/', '/assets/js/', '/static/js/',
            '/bundles/', '/chunks/', '/webpack/', '/dist/',
            'jquery', 'bootstrap', 'react', 'vue', 'angular',
            'app.', 'main.', 'bundle.', 'chunk.', 'vendor.',
            'min.js', 'prod.js'
        ]
        
        if any(pattern in path for pattern in js_patterns):
            return True
            
        # Very long random-looking paths (like the DraftKings example)
        if len(path) > 20 and '/' in path:
            # Check for base64-like or encoded patterns
            path_parts = [p for p in path.split('/') if p]
            if any(len(part) > 10 and part.replace('-', '').replace('_', '').isalnum() for part in path_parts):
                return True
        
        # API endpoints - these should be treated as "other" URLs, not JS
        api_patterns = [
            '/api/', '/v1/', '/v2/', '/v3/', '/rest/', '/graphql',
            '.json', '.xml', '/users/', '/notifications/'
        ]
        
        if any(pattern in path for pattern in api_patterns):
            return False  # These are API endpoints, not JS files
                
        return False

    async def fetch_url(self, url: str) -> Optional[str]:
        """Fetch URL content with error handling"""
        try:
            # Skip image files completely - they're not useful for our analysis
            if any(url.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp']):
                return None
                
            async with self.session.get(url) as response:
                if response.status == 200:
                    content = await response.text()
                    self.logger.debug(f"Fetched: {url}")
                    return content
                else:
                    if not self.silent:  # Only log warnings in non-silent mode
                        self.logger.warning(f"Failed to fetch {url}: HTTP {response.status}")
                    return None
        except UnicodeDecodeError as e:
            # Image files or binary content - skip silently
            return None
        except Exception as e:
            if not self.silent:  # Only log errors in non-silent mode
                self.logger.error(f"Error fetching {url}: {e}")
            return None

    async def process_js_file(self, url: str, content: str) -> Dict[str, Any]:
        """Process a JavaScript file and extract information"""
        results = {
            'js_urls': [],
            'other_urls': [],
            'secrets': [],
            'api_endpoints': [],
            'api_patterns': []
        }
        
        # Extract URLs using jsluice
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
            f.write(content)
            temp_file = f.name
        
        try:
            # Extract URLs
            urls_cmd = ['jsluice', 'urls', '-R', url, temp_file]
            url_lines = await self.jsluice.run_jsluice_command(urls_cmd)
            
            for line in url_lines:
                line = line.strip()
                if line:
                    try:
                        # Try to parse as JSON first (jsluice sometimes returns JSON)
                        if line.startswith('{'):
                            data = json.loads(line)
                            extracted_url = data.get('url', '')
                        else:
                            extracted_url = line
                        
                        # Clean up the URL and validate
                        if extracted_url and self._is_interesting_url(extracted_url):
                            if self._is_likely_js_url(extracted_url):
                                results['js_urls'].append(extracted_url)
                            else:
                                results['other_urls'].append(extracted_url)
                    except (json.JSONDecodeError, KeyError):
                        # If JSON parsing fails, treat as plain URL
                        if self._is_interesting_url(line):
                            if self._is_likely_js_url(line):
                                results['js_urls'].append(line)
                            else:
                                results['other_urls'].append(line)
            
            # Extract secrets
            secrets_cmd = ['jsluice', 'secrets', '-R', url, temp_file]
            secret_lines = await self.jsluice.run_jsluice_command(secrets_cmd)
            results['secrets'] = [line.strip() for line in secret_lines if line.strip()]
            
            # Look for API patterns
            if self.debug_queries:
                self.logger.debug(f"Running API queries on JavaScript file: {url}")
                self.logger.debug(f"Content length: {len(content)} characters")
                self.logger.debug(f"Content snippet: {content[:200]}...")
            
            api_patterns_raw = await self.jsluice.run_api_queries(url, content)
            
            # If tree-sitter queries didn't find much, try regex fallback
            if len(api_patterns_raw) == 0:
                if self.debug_queries:
                    self.logger.debug("No patterns from tree-sitter queries, trying regex fallback")
                regex_patterns = self.jsluice._find_api_patterns_regex(content, url)
                if self.debug_queries and regex_patterns:
                    self.logger.debug(f"Regex fallback found: {len(regex_patterns)} patterns")
                api_patterns_raw.extend(regex_patterns)
            
            # Reconstruct API calls from patterns
            reconstructed_calls = self._reconstruct_api_calls(api_patterns_raw)
            formatted_patterns = self._format_api_patterns(reconstructed_calls)
            
            if self.debug_queries:
                self.logger.debug(f"Total reconstructed calls: {len(reconstructed_calls)}")
                self.logger.debug(f"Formatted API patterns: {len(formatted_patterns)}")
            
            results['api_patterns'] = formatted_patterns
            
        finally:
            try:
                os.unlink(temp_file)
            except:
                pass
        
        return results

    def _reconstruct_api_calls(self, patterns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Reconstruct complete API calls from tree-sitter query results"""
        calls = []
        
        for pattern in patterns:
            call = {
                'type': 'unknown',
                'url': '',
                'method': 'GET',
                'source_file': pattern.get('original_file', ''),
                'query_type': pattern.get('query_type', ''),
                'raw_pattern': pattern
            }
            
            # Determine call type and extract URL
            if pattern.get('func') == 'fetch':
                call['type'] = 'fetch'
                call['url'] = pattern.get('url', '')
            elif pattern.get('method') == 'fetch':
                call['type'] = 'fetch'
                call['url'] = pattern.get('url', '')
            elif pattern.get('method') == 'open':
                call['type'] = 'xhr'
                call['method'] = pattern.get('http_method', 'GET').upper()
                call['url'] = pattern.get('url', '')
            elif 'axios' in str(pattern.get('obj', '')).lower():
                call['type'] = 'axios'
                call['method'] = pattern.get('method', 'GET').upper()
                call['url'] = pattern.get('url', '')
            elif pattern.get('constructor') == 'WebSocket':
                call['type'] = 'websocket'
                call['url'] = pattern.get('url', '')
            elif pattern.get('api_string'):
                call['type'] = 'string_pattern'
                call['url'] = pattern.get('api_string', '')
            
            # Only include calls with valid URLs
            if call['url'] and len(call['url']) > 5:
                calls.append(call)
        
        return calls

    def _format_api_patterns(self, calls: List[Dict[str, Any]]) -> List[str]:
        """Format API calls for display"""
        formatted = []
        
        for call in calls:
            if call['type'] == 'fetch':
                formatted.append(f"fetch('{call['url']}')")
            elif call['type'] == 'xhr':
                formatted.append(f"xhr.open('{call['method']}', '{call['url']}')")
            elif call['type'] == 'axios':
                formatted.append(f"axios.{call['method'].lower()}('{call['url']}')")
            elif call['type'] == 'websocket':
                formatted.append(f"new WebSocket('{call['url']}')")
            elif call['type'] == 'string_pattern':
                formatted.append(f"URL: {call['url']}")
            else:
                formatted.append(f"API: {call['url']}")
        
        return formatted

    async def process_url(self, url: str, depth: int = 0, max_depth: int = 1) -> Dict[str, Any]:
        """Process a URL and optionally follow JS links"""
        if not self._is_likely_js_url(url):
            if self.debug_queries:
                self.logger.debug(f"URL doesn't look like JS, but allowing based on pattern: {url}")
        
        self.logger.info(f"Processing (depth {depth}): {url}")
        
        content = await self.fetch_url(url)
        if not content:
            return {}
        
        results = await self.process_js_file(url, content)
        
        # Follow JS URLs if we haven't reached max depth
        if depth < max_depth and results['js_urls']:
            for js_url in results['js_urls'][:5]:  # Limit to prevent infinite recursion
                try:
                    # Clean and validate the URL before processing
                    if not js_url.startswith(('http://', 'https://')):
                        if js_url.startswith('/'):
                            # Relative URL - construct absolute URL
                            parsed_base = urlparse(url)
                            absolute_url = f"{parsed_base.scheme}://{parsed_base.netloc}{js_url}"
                        else:
                            # Relative URL without leading slash
                            absolute_url = urljoin(url, js_url)
                    else:
                        absolute_url = js_url
                    
                    # Additional validation - make sure it's a reasonable URL
                    if self._is_interesting_url(absolute_url) and len(absolute_url) < 500:
                        child_results = await self.process_url(absolute_url, depth + 1, max_depth)
                        
                        # Merge results
                        for key in ['js_urls', 'other_urls', 'secrets', 'api_endpoints', 'api_patterns']:
                            if key in child_results:
                                results[key].extend(child_results[key])
                    else:
                        if self.debug_queries:
                            self.logger.debug(f"Skipping invalid/too-long URL: {absolute_url}")
                            
                except Exception as e:
                    self.logger.error(f"Error processing child URL {js_url}: {e}")
        
        return results

    def print_results(self, results: Dict[str, Any]):
        """Print results in a formatted way"""
        # Remove duplicates while preserving order
        unique_js_urls = list(dict.fromkeys(results.get('js_urls', [])))
        unique_other_urls = list(dict.fromkeys(results.get('other_urls', [])))
        unique_secrets = list(dict.fromkeys(results.get('secrets', [])))
        unique_api_endpoints = list(dict.fromkeys(results.get('api_endpoints', [])))
        unique_api_patterns = list(dict.fromkeys(results.get('api_patterns', [])))
        
        if self.silent:
            # Silent mode: just output raw URLs/secrets without prefixes or summary
            for js_url in unique_js_urls:
                print(js_url)
            for other_url in unique_other_urls:
                print(other_url)
            for secret in unique_secrets:
                print(secret)
            for endpoint in unique_api_endpoints:
                print(endpoint)
            # For patterns, extract just the URL part
            for pattern in unique_api_patterns:
                if pattern.startswith('URL: '):
                    print(pattern[5:])  # Remove "URL: " prefix
                else:
                    print(pattern)
        else:
            # Normal mode: formatted output with summary
            total_js = len(unique_js_urls)
            total_other = len(unique_other_urls)
            total_secrets = len(unique_secrets)
            total_api_endpoints = len(unique_api_endpoints)
            total_api_patterns = len(unique_api_patterns)
            
            self.logger.info(f"Found: {total_js} JS URLs, {total_other} other URLs, {total_secrets} secrets, {total_api_endpoints} API endpoints, {total_api_patterns} API patterns")
            
            # Print JS URLs (clean format)
            for js_url in unique_js_urls:
                print(f"JS: {js_url}")
            
            # Print other URLs (clean format) 
            for other_url in unique_other_urls:
                print(f"URL: {other_url}")
            
            # Print secrets
            for secret in unique_secrets:
                print(f"SECRET: {secret}")
            
            # Print API endpoints
            for endpoint in unique_api_endpoints:
                print(f"API: {endpoint}")
            
            # Print API patterns (clean format)
            for pattern in unique_api_patterns:
                print(f"PATTERN: {pattern}")

async def main():
    parser = argparse.ArgumentParser(description='GoFuzz - JavaScript security analysis tool')
    parser.add_argument('--js-only', action='store_true', help='Only analyze JS files')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--debug-queries', action='store_true', help='Enable debug logging for tree-sitter queries')
    parser.add_argument('--silent', action='store_true', help='Silent mode - output only URLs/secrets without prefixes or summary')
    parser.add_argument('--max-depth', type=int, default=3, help='Maximum depth for following JS includes (default: 3)')
    
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
    
    async with GoFuzz(debug=args.debug, debug_queries=args.debug_queries, silent=args.silent) as gofuzz:
        for url in urls:
            try:
                results = await gofuzz.process_url(url, max_depth=args.max_depth)
                gofuzz.print_results(results)
            except Exception as e:
                gofuzz.logger.error(f"Error processing {url}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
