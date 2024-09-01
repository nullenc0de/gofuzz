import json
import sys
import urllib.parse
import argparse
from collections import OrderedDict
import asyncio
import aiohttp
import tempfile
import os
import subprocess
import re

def normalize_url(url, base_url):
    if url.startswith('//'):
        return 'https:' + url
    elif not url.startswith(('http://', 'https://')):
        return urllib.parse.urljoin(base_url, url)
    return url

def is_js_file(url):
    return '.js' in url.lower()

async def run_jsluice(url, mode, session, verbose):
    try:
        async with session.get(url, timeout=30) as response:
            content = await response.text()
            if verbose:
                print(f"Fetched: {url}")

            with tempfile.NamedTemporaryFile(mode='w+', delete=False) as temp_file:
                temp_file.write(content)
                temp_file_path = temp_file.name

            cmd = f"jsluice {mode} -R '{url}' {temp_file_path}"
            if verbose:
                print(f"Running command: {cmd}")
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            os.unlink(temp_file_path)  # Remove the temporary file

            if stderr and verbose:
                print(f"Error processing {url}: {stderr.decode()}", file=sys.stderr)
            return stdout.decode().splitlines(), content
    except Exception as e:
        if verbose:
            print(f"Error in run_jsluice for {url}: {str(e)}", file=sys.stderr)
        return [], ""

def run_nuclei(file_path, original_url, verbose):
    try:
        cmd = f"nuclei -target {file_path} -t file/keys -eid credential-exposure-file -jsonl"
        if verbose:
            print(f"Running command: {cmd}")
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        return process_nuclei_output(result.stdout.splitlines(), original_url)
    except subprocess.CalledProcessError as e:
        if verbose:
            print(f"Error running Nuclei: {e}", file=sys.stderr)
        return []

def process_nuclei_output(nuclei_output, original_url):
    processed_secrets = []
    for line in nuclei_output:
        try:
            nuclei_data = json.loads(line)
            if 'info' not in nuclei_data or 'extracted-results' not in nuclei_data:
                continue
            
            for result in nuclei_data['extracted-results']:
                secret = {
                    'kind': f"Nuclei_{nuclei_data['info']['name'].replace(' ', '')}",
                    'data': {
                        'key': result,
                        'template': nuclei_data['template-id'],
                        'matched-at': nuclei_data['matched-at']
                    },
                    'filename': nuclei_data['path'],
                    'severity': nuclei_data['info']['severity'],
                    'context': None,
                    'original_file': original_url
                }
                processed_secrets.append(secret)
        except json.JSONDecodeError:
            print(f"Error decoding Nuclei JSON: {line}", file=sys.stderr)
    return processed_secrets

async def process_jsluice_output(jsluice_output, current_url, content, verbose, use_nuclei):
    js_urls = set()
    non_js_urls = set()
    secrets = []
    api_endpoints = set()

    if verbose:
        print(f"Processing output for {current_url}")
        print(f"JSluice output lines: {len(jsluice_output)}")

    for line in jsluice_output:
        try:
            data = json.loads(line)
            if 'url' in data:
                url = normalize_url(data['url'], current_url)
                parsed_url = urllib.parse.urlparse(url)
                if parsed_url.scheme and parsed_url.netloc:
                    new_url = urllib.parse.urlunparse((
                        parsed_url.scheme,
                        parsed_url.netloc,
                        parsed_url.path,
                        parsed_url.params,
                        parsed_url.query,
                        parsed_url.fragment
                    ))
                    if is_js_file(new_url):
                        js_urls.add(new_url)
                    else:
                        non_js_urls.add(new_url)
                    
                    # Check for API endpoints
                    if re.search(r'/api/|/v\d+/', parsed_url.path):
                        api_endpoints.add(new_url)
            elif 'kind' in data:
                data['original_file'] = current_url
                secrets.append(data)
        except json.JSONDecodeError:
            if verbose:
                print(f"Error decoding JSON: {line}", file=sys.stderr)

    if use_nuclei:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name

        nuclei_secrets = run_nuclei(temp_file_path, current_url, verbose)
        secrets.extend(nuclei_secrets)
        
        os.unlink(temp_file_path)  # Remove the temporary file

    if verbose:
        print(f"Found {len(js_urls)} JavaScript URLs")
        print(f"Found {len(non_js_urls)} non-JavaScript URLs")
        print(f"Found {len(secrets)} secrets")
        print(f"Found {len(api_endpoints)} potential API endpoints")

    return js_urls, non_js_urls, secrets, api_endpoints

async def recursive_process(initial_url, session, processed_urls, verbose, use_nuclei):
    if initial_url in processed_urls:
        return set(), set(), [], set()
    processed_urls.add(initial_url)

    urls_output, content = await run_jsluice(initial_url, 'urls', session, verbose)
    secrets_output, _ = await run_jsluice(initial_url, 'secrets', session, verbose)

    js_urls, non_js_urls, secrets, api_endpoints = await process_jsluice_output(urls_output + secrets_output, initial_url, content, verbose, use_nuclei)

    tasks = []
    for url in js_urls:
        if url not in processed_urls:
            tasks.append(recursive_process(url, session, processed_urls, verbose, use_nuclei))

    results = await asyncio.gather(*tasks)

    for result_js_urls, result_non_js_urls, result_secrets, result_api_endpoints in results:
        js_urls.update(result_js_urls)
        non_js_urls.update(result_non_js_urls)
        secrets.extend(result_secrets)
        api_endpoints.update(result_api_endpoints)

    return js_urls, non_js_urls, secrets, api_endpoints

def severity_to_int(severity):
    severity_map = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1, 'info': 0}
    return severity_map.get(severity.lower(), -1)

async def main():
    parser = argparse.ArgumentParser(description="JSluice URL and Secrets Processor")
    parser.add_argument('-m', '--mode', choices=['endpoints', 'secrets', 'both', 'api'], default='both',
                        help="Specify what to hunt for: endpoints, secrets, both, or api (default: both)")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Enable verbose output")
    parser.add_argument('-n', '--nuclei', action='store_true',
                        help="Use Nuclei for additional secret detection")
    parser.add_argument('-s', '--silent', action='store_true',
                        help="Enable silent mode (no headers, mixed output)")
    args = parser.parse_args()

    all_urls = set()
    all_secrets = []
    all_api_endpoints = set()
    processed_urls = set()

    async with aiohttp.ClientSession() as session:
        tasks = []
        for initial_url in sys.stdin:
            initial_url = initial_url.strip()
            if initial_url:
                tasks.append(recursive_process(initial_url, session, processed_urls, args.verbose, args.nuclei))

        results = await asyncio.gather(*tasks)

        for js_urls, non_js_urls, secrets, api_endpoints in results:
            all_urls.update(non_js_urls)
            all_secrets.extend(secrets)
            all_api_endpoints.update(api_endpoints)

    if args.mode in ['endpoints', 'both', 'api']:
        for url in sorted(all_urls):
            if args.silent:
                print(url)
            else:
                print(f"URL: {url}")
        
        for endpoint in sorted(all_api_endpoints):
            if args.silent:
                print(endpoint)
            else:
                print(f"API Endpoint: {endpoint}")

    if args.mode in ['secrets', 'both']:
        sorted_secrets = sorted(all_secrets, key=lambda x: (-severity_to_int(x['severity']), json.dumps(x)))
        unique_secrets = list(OrderedDict((json.dumps(secret), secret) for secret in sorted_secrets).values())

        for secret in unique_secrets:
            if args.silent:
                print(json.dumps(secret))
            else:
                print(f"Secret: {json.dumps(secret)}")

    if args.verbose:
        print(f"\nTotal URLs processed: {len(processed_urls)}")
        print(f"Total unique non-JS URLs found: {len(all_urls)}")
        print(f"Total secrets found: {len(all_secrets)}")
        print(f"Total potential API endpoints found: {len(all_api_endpoints)}")

if __name__ == "__main__":
    asyncio.run(main())
