import json
import sys
import urllib.parse
import argparse
from collections import OrderedDict
import asyncio
import aiohttp
import tempfile
import os
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
        print(f"Error in run_jsluice for {url}: {str(e)}", file=sys.stderr)
        return [], ""

async def process_jsluice_output(jsluice_output, current_url, content, verbose):
    js_urls = set()
    non_js_urls = set()
    secrets = []

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
            elif 'kind' in data:
                data['original_file'] = current_url
                secrets.append(data)
        except json.JSONDecodeError:
            if verbose:
                print(f"Error decoding JSON: {line}", file=sys.stderr)

    if verbose:
        print(f"Found {len(js_urls)} JavaScript URLs")
        print(f"Found {len(non_js_urls)} non-JavaScript URLs")
        print(f"Found {len(secrets)} secrets from JSluice")

    # Add custom checks
    secrets.extend(check_aws_cognito(content, current_url))
    secrets.extend(check_razorpay(content, current_url))
    secrets.extend(check_mapbox(content, current_url))
    secrets.extend(check_fcm(content, current_url))
    secrets.extend(check_digitalocean(content, current_url))
    secrets.extend(check_tugboat(content, current_url))

    if verbose:
        print(f"Total secrets after custom checks: {len(secrets)}")

    return js_urls, non_js_urls, secrets

def check_aws_cognito(content, current_url):
    secrets = []
    cognito_markers = [
        'identityPoolId', 'cognitoIdentityPoolId', 'userPoolWebClientId', 'userPoolId',
        'aws_user_pools_id', 'aws_cognito_identity_pool_id', 'AWSCognitoIdentityProviderService',
        'CognitoIdentityCredentials', 'AWS.CognitoIdentityServiceProvider', 'cognitoUser'
    ]

    for marker in cognito_markers:
        match = re.search(rf'{marker}\s*[=:]\s*["\']?([^"\']+)["\']?', content)
        if match:
            secrets.append({
                'kind': 'AWSCognitoMisconfiguration',
                'data': {'marker': marker, 'matched_string': match.group()},
                'filename': current_url,
                'severity': 'high',
                'context': None
            })

    pool_id_regex = r'(us|ap|ca|cn|eu|sa)-[a-z]+-\d:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'
    pool_ids = re.finditer(pool_id_regex, content)
    for match in pool_ids:
        secrets.append({
            'kind': 'AWSCognitoPoolID',
            'data': {'value': match.group(), 'matched_string': match.group()},
            'filename': current_url,
            'severity': 'high',
            'context': None
        })

    partial_pool_id_regex = r'(us|ap|ca|cn|eu|sa)-[a-z]+-\d[:\w-]{10,}'
    partial_pool_ids = re.finditer(partial_pool_id_regex, content)
    for match in partial_pool_ids:
        if match.group() not in [s['data']['value'] for s in secrets if s['kind'] == 'AWSCognitoPoolID']:
            secrets.append({
                'kind': 'PossibleAWSCognitoPoolID',
                'data': {'value': match.group(), 'matched_string': match.group()},
                'filename': current_url,
                'severity': 'medium',
                'context': None
            })

    return secrets

def check_razorpay(content, current_url):
    secrets = []
    razorpay_regex = r"(rzp_(live|test)_[a-zA-Z0-9]{14})"
    razorpay_matches = re.finditer(razorpay_regex, content)
    for match in razorpay_matches:
        secrets.append({
            'kind': 'RazorpayClientID',
            'data': {'value': match.group(1), 'matched_string': match.group()},
            'filename': current_url,
            'severity': 'high',
            'context': None
        })
    return secrets

def check_mapbox(content, current_url):
    secrets = []
    mapbox_regex = r'(sk\.eyJ1Ijoi\w+\.[\w-]*)'
    mapbox_matches = re.finditer(mapbox_regex, content)
    for match in mapbox_matches:
        secrets.append({
            'kind': 'MapboxToken',
            'data': {'value': match.group(1), 'matched_string': match.group()},
            'filename': current_url,
            'severity': 'medium',
            'context': None
        })
    return secrets

def check_fcm(content, current_url):
    secrets = []
    fcm_regex = r"(AAAA[a-zA-Z0-9_-]{7}:[a-zA-Z0-9_-]{140})"
    fcm_matches = re.finditer(fcm_regex, content)
    for match in fcm_matches:
        secrets.append({
            'kind': 'FCMServerKey',
            'data': {'value': match.group(1), 'matched_string': match.group()},
            'filename': current_url,
            'severity': 'high',
            'context': None
        })
    return secrets

def check_digitalocean(content, current_url):
    secrets = []
    do_key_regex = r'"do_key"\s*:\s*"([^"]+)"'
    do_key_matches = re.finditer(do_key_regex, content)
    for match in do_key_matches:
        secrets.append({
            'kind': 'DigitalOceanKey',
            'data': {'value': match.group(1), 'matched_string': match.group()},
            'filename': current_url,
            'severity': 'critical',
            'context': None
        })
    return secrets

def check_tugboat(content, current_url):
    secrets = []
    
    # Check if all required words are present
    required_words = ["authentication", "access_token", "ssh_user"]
    if all(word in content for word in required_words):
        # Use the specific regex pattern from the YAML
        tugboat_regex = r'access_token:\s*(.*)'
        tugboat_matches = re.findall(tugboat_regex, content)
        
        for match in tugboat_matches:
            secrets.append({
                'kind': 'TugboatConfig',
                'data': {
                    'value': match,
                    'matched_string': f'access_token: {match}'
                },
                'filename': current_url,
                'severity': 'critical',
                'context': None
            })
    
    return secrets

async def recursive_process(initial_url, session, processed_urls, verbose):
    if initial_url in processed_urls:
        return set(), set(), []
    processed_urls.add(initial_url)

    urls_output, content = await run_jsluice(initial_url, 'urls', session, verbose)
    secrets_output, _ = await run_jsluice(initial_url, 'secrets', session, verbose)

    js_urls, non_js_urls, secrets = await process_jsluice_output(urls_output + secrets_output, initial_url, content, verbose)

    tasks = []
    for url in js_urls:
        if url not in processed_urls:
            tasks.append(recursive_process(url, session, processed_urls, verbose))

    results = await asyncio.gather(*tasks)

    for result_js_urls, result_non_js_urls, result_secrets in results:
        js_urls.update(result_js_urls)
        non_js_urls.update(result_non_js_urls)
        secrets.extend(result_secrets)

    return js_urls, non_js_urls, secrets

def severity_to_int(severity):
    severity_map = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1, 'info': 0}
    return severity_map.get(severity.lower(), -1)

async def main():
    parser = argparse.ArgumentParser(description="JSluice URL and Secrets Processor")
    parser.add_argument('-m', '--mode', choices=['endpoints', 'secrets', 'both'], default='both',
                        help="Specify what to hunt for: endpoints, secrets, or both (default: both)")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Enable verbose output")
    args = parser.parse_args()

    all_urls = set()
    all_secrets = []
    processed_urls = set()

    async with aiohttp.ClientSession() as session:
        tasks = []
        for initial_url in sys.stdin:
            initial_url = initial_url.strip()
            if initial_url:
                tasks.append(recursive_process(initial_url, session, processed_urls, args.verbose))

        results = await asyncio.gather(*tasks)

        for js_urls, non_js_urls, secrets in results:
            all_urls.update(non_js_urls)
            all_secrets.extend(secrets)

    if args.mode in ['endpoints', 'both']:
        for url in sorted(all_urls):
            print(url)

    if args.mode in ['secrets', 'both']:
        sorted_secrets = sorted(all_secrets, key=lambda x: (-severity_to_int(x['severity']), json.dumps(x)))
        unique_secrets = list(OrderedDict((json.dumps(secret), secret) for secret in sorted_secrets).values())

        for secret in unique_secrets:
            print(json.dumps(secret))

    if args.verbose:
        print(f"Total URLs processed: {len(processed_urls)}")
        print(f"Total unique non-JS URLs found: {len(all_urls)}")
        print(f"Total secrets found: {len(all_secrets)}")

if __name__ == "__main__":
    asyncio.run(main())
