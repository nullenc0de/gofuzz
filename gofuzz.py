import json
import sys
import urllib.parse
import subprocess
import re

def run_jsluice(url):
    cmd = f"jsluice urls -R '{url}' <(curl -sk '{url}')"
    result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
    return result.stdout.splitlines()

def is_js_file(url):
    return url.lower().endswith('.js')

def process_jsluice_output(jsluice_output, processed_urls, non_js_urls):
    js_urls = set()
    for line in jsluice_output:
        try:
            data = json.loads(line)
            url = data.get('url', '')
            
            # Parse the URL
            parsed_url = urllib.parse.urlparse(url)
            
            # Check if the URL is valid and has a scheme
            if parsed_url.scheme and parsed_url.netloc:
                # Parse existing query parameters
                existing_params = urllib.parse.parse_qs(parsed_url.query)
                
                # Get queryParams from JSON data
                json_params = data.get('queryParams', [])
                
                # Merge existing params with JSON params
                for param in json_params:
                    if param not in existing_params:
                        existing_params[param] = ['']
                
                # Reconstruct the query string
                new_query = urllib.parse.urlencode(existing_params, doseq=True)
                
                # Construct the new URL
                new_url = urllib.parse.urlunparse((
                    parsed_url.scheme,
                    parsed_url.netloc,
                    parsed_url.path,
                    parsed_url.params,
                    new_query,
                    parsed_url.fragment
                ))
                
                if is_js_file(new_url) and new_url not in processed_urls:
                    js_urls.add(new_url)
                else:
                    non_js_urls.add(new_url)
        except json.JSONDecodeError:
            print(f"Error decoding JSON: {line}", file=sys.stderr)
    
    return js_urls

def recursive_process(initial_url):
    processed_urls = set()
    non_js_urls = set()
    urls_to_process = {initial_url}

    while urls_to_process:
        current_url = urls_to_process.pop()
        processed_urls.add(current_url)
        
        jsluice_output = run_jsluice(current_url)
        new_js_urls = process_jsluice_output(jsluice_output, processed_urls, non_js_urls)
        
        urls_to_process.update(new_js_urls - processed_urls)

    return non_js_urls

if __name__ == "__main__":
    for initial_url in sys.stdin:
        initial_url = initial_url.strip()
        if initial_url:
            result_urls = recursive_process(initial_url)
            for url in sorted(result_urls):
                print(url)
