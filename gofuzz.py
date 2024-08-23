import json
import sys
import urllib.parse
import argparse
from collections import OrderedDict
import asyncio
import aiohttp
import tempfile
import os

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
            return stdout.decode().splitlines()
    except Exception as e:
        if verbose:
            print(f"Error fetching {url}: {str(e)}", file=sys.stderr)
        return []

def is_js_file(url):
    return '.js' in url.lower()

def normalize_url(url, base_url):
    if url.startswith('//'):
        return 'https:' + url
    elif not url.startswith(('http://', 'https://')):
        return urllib.parse.urljoin(base_url, url)
    return url

async def process_jsluice_output(jsluice_output, current_url, verbose):
    js_urls = set()
    non_js_urls = set()
    secrets = []
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
        print(f"Processed {current_url}:")
        print(f"  Found {len(js_urls)} JavaScript URLs")
        print(f"  Found {len(non_js_urls)} non-JavaScript URLs")
        print(f"  Found {len(secrets)} secrets")

    return js_urls, non_js_urls, secrets

async def recursive_process(initial_url, session, processed_urls, verbose):
    if initial_url in processed_urls:
        return set(), set(), []
    processed_urls.add(initial_url)

    urls_output = await run_jsluice(initial_url, 'urls', session, verbose)
    secrets_output = await run_jsluice(initial_url, 'secrets', session, verbose)

    js_urls, non_js_urls, secrets = await process_jsluice_output(urls_output + secrets_output, initial_url, verbose)

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

if __name__ == "__main__":
    asyncio.run(main())
