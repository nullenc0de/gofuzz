import json
import sys
import urllib.parse
import subprocess
import re

def run_jsluice(url, mode):
    cmd = f"jsluice {mode} -R '{url}' <(curl -sk '{url}')"
    result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
    return result.stdout.splitlines()

def is_js_file(url):
    return url.lower().endswith('.js')

def process_jsluice_output(jsluice_output, processed_urls, non_js_urls, secrets):
    js_urls = set()
    for line in jsluice_output:
        try:
            data = json.loads(line)
            if 'url' in data:
                url = data['url']
                
                # Parse the URL
                parsed_url = urllib.parse.urlparse(url)
                
                # Check if the URL is valid and has a scheme
                if parsed_url.scheme and parsed_url.netloc:
                    # Construct the new URL
                    new_url = urllib.parse.urlunparse((
                        parsed_url.scheme,
                        parsed_url.netloc,
                        parsed_url.path,
                        parsed_url.params,
                        parsed_url.query,
                        parsed_url.fragment
                    ))
                    
                    if is_js_file(new_url) and new_url not in processed_urls:
                        js_urls.add(new_url)
                    else:
                        non_js_urls.add(new_url)
            elif 'kind' in data:
                # This is a secret
                secrets.append(data)
        except json.JSONDecodeError:
            print(f"Error decoding JSON: {line}", file=sys.stderr)
    
    return js_urls

def recursive_process(initial_url):
    processed_urls = set()
    non_js_urls = set()
    secrets = []
    urls_to_process = {initial_url}

    while urls_to_process:
        current_url = urls_to_process.pop()
        processed_urls.add(current_url)
        
        urls_output = run_jsluice(current_url, 'urls')
        secrets_output = run_jsluice(current_url, 'secrets')
        
        new_js_urls = process_jsluice_output(urls_output, processed_urls, non_js_urls, secrets)
        process_jsluice_output(secrets_output, processed_urls, non_js_urls, secrets)
        
        urls_to_process.update(new_js_urls - processed_urls)

    return non_js_urls, secrets

if __name__ == "__main__":
    all_urls = set()
    all_secrets = []

    for initial_url in sys.stdin:
        initial_url = initial_url.strip()
        if initial_url:
            result_urls, result_secrets = recursive_process(initial_url)
            all_urls.update(result_urls)
            all_secrets.extend(result_secrets)

    print("URLs:")
    for url in sorted(all_urls):
        print(url)

    print("\nSecrets:")
    for secret in all_secrets:
        print(json.dumps(secret))
