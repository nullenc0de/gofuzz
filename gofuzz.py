import argparse
import json
import sys
import requests
import re
from urllib.parse import urlparse, parse_qs, urlencode

def is_js_file(url):
    return url.lower().endswith('.js')

def extract_urls_and_params(content):
    url_pattern = re.compile(r'(https?://[^\s\'"]+)')
    param_pattern = re.compile(r'["\'](\w+)["\']:\s*["\']?([^"\'\s]+)["\']?')
    
    urls = url_pattern.findall(content)
    params = param_pattern.findall(content)
    
    return urls, [param for param, _ in params]

def limit_params(params, max_params=30):
    return params[:max_params]

def generate_fuzzed_url(url, params):
    parsed_url = urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
    
    limited_params = limit_params(params)
    
    query_params = {param: "FUZZ" for param in limited_params}
    query_string = urlencode(query_params)
    
    fuzzed_url = f"{base_url}?{query_string}"
    
    return fuzzed_url

def process_content(content):
    urls, params = extract_urls_and_params(content)
    
    fuzzed_urls = set()
    for extracted_url in urls:
        fuzzed_url = generate_fuzzed_url(extracted_url, params)
        fuzzed_urls.add(fuzzed_url)
    
    return fuzzed_urls

def process_url(url):
    if not is_js_file(url):
        print(f"Skipping non-JS file: {url}", file=sys.stderr)
        return set()

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return set()

    return process_content(response.text)

def main():
    parser = argparse.ArgumentParser(description="Generate fuzzed URLs from JS content")
    parser.add_argument("-i", "--input", help="Input file containing URLs (optional, uses stdin if not provided)")
    parser.add_argument("-o", "--output", help="Output file for fuzzed URLs (default: stdout)")
    args = parser.parse_args()

    if args.input:
        with open(args.input, 'r') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        all_fuzzed_urls = set()
        for url in urls:
            print(f"Processing: {url}", file=sys.stderr)
            fuzzed = process_url(url)
            all_fuzzed_urls.update(fuzzed)
            print(f"Found {len(fuzzed)} fuzzed URLs for {url}", file=sys.stderr)
    else:
        content = sys.stdin.read()
        all_fuzzed_urls = process_content(content)

    if args.output:
        with open(args.output, 'w') as f:
            for url in sorted(all_fuzzed_urls):
                f.write(f"{url}\n")
        print(f"Wrote {len(all_fuzzed_urls)} URLs to {args.output}", file=sys.stderr)
    else:
        for url in sorted(all_fuzzed_urls):
            print(url)

    print(f"Generated {len(all_fuzzed_urls)} total fuzzed URLs", file=sys.stderr)

if __name__ == "__main__":
    main()
