import json
import sys
import urllib.parse
import subprocess

def run_jsluice(url):
    cmd = f"jsluice urls -R '{url}' <(curl -sk '{url}')"
    result = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True)
    return result.stdout.splitlines()

def process_jsluice_output(jsluice_output):
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
                
                print(new_url)
        except json.JSONDecodeError:
            print(f"Error decoding JSON: {line}", file=sys.stderr)

if __name__ == "__main__":
    for url in sys.stdin:
        url = url.strip()
        jsluice_output = run_jsluice(url)
        process_jsluice_output(jsluice_output)
