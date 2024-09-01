# JSluice and Nuclei Integration Script

This script is a powerful tool that recursively processes JavaScript files to extract URLs and secrets using both the JSluice command-line utility and Nuclei. It starts with an initial URL, processes all JavaScript files it encounters, and outputs a comprehensive list of unique URLs and any secrets found, sorted by severity.

## Features

- Recursively processes JavaScript files
- Extracts URLs from various JavaScript contexts using JSluice
- Detects secrets (API keys, tokens, etc.) in JavaScript files using both JSluice and Nuclei
- Resolves relative URLs to absolute URLs
- Outputs unique URLs and secrets without headers
- Allows specifying whether to hunt for endpoints, secrets, or both
- Sorts secrets by severity (highest to lowest)
- Removes duplicate secrets
- Includes information about the original JS file where each secret was found
- Integrates Nuclei for additional credential exposure detection

## Prerequisites

- Python 3.6+
- JSluice command-line tool
- Nuclei
- `aiohttp` Python library

## Installation

1. Ensure you have Python 3.6+ installed on your system.
2. Install the JSluice command-line tool. (Refer to the JSluice documentation for installation instructions)
3. Install Nuclei. (Refer to the Nuclei documentation for installation instructions)
4. Install the required Python library:

   ```
   pip install aiohttp
   ```

5. Download the script (e.g., `jsluice_nuclei_processor.py`).

## Usage

You can use the script in two ways:

1. Process a single URL:

   ```
   echo "https://example.com/script.js" | python jsluice_nuclei_processor.py [options]
   ```

2. Process multiple URLs from a file:

   ```
   cat js_urls.txt | python jsluice_nuclei_processor.py [options]
   ```

### Options

- `-m {endpoints,secrets,both}`, `--mode {endpoints,secrets,both}`: Specify what to hunt for: endpoints, secrets, or both (default: both)
- `-v`, `--verbose`: Enable verbose output
- `-n`, `--nuclei`: Use Nuclei for additional secret detection

Examples:

- To hunt for endpoints only:
  ```
  echo "https://example.com/script.js" | python jsluice_nuclei_processor.py -m endpoints
  ```

- To hunt for secrets only, using both JSluice and Nuclei:
  ```
  echo "https://example.com/script.js" | python jsluice_nuclei_processor.py -m secrets -n
  ```

- To hunt for both endpoints and secrets, with verbose output:
  ```
  echo "https://example.com/script.js" | python jsluice_nuclei_processor.py -m both -v -n
  ```

## Output

The script outputs directly to stdout without headers:

1. When hunting for endpoints (or both), it outputs a sorted list of unique URLs, one per line.
2. When hunting for secrets (or both), it outputs JSON objects representing the secrets, one per line. Secrets are sorted by severity (highest to lowest) and duplicates are removed.

Example output for secrets:

```json
{"kind": "AWSAccessKey", "data": {"key": "AKIAIOSFODNN7EXAMPLE", "secret": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}, "filename": "https://example.com/config.js", "severity": "high", "context": {"awsRegion": "us-west-2", "bucketName": "example-uploads"}, "original_file": "https://example.com/main.js"}
{"kind": "Nuclei_CredentialExposure", "data": {"key": "api_key=AIzaSyC3xbj4UeWLQ2I5lxZpJFkfLwkbhcheQ4E", "template": "credential-exposure-file", "matched-at": "/tmp/tmpfile123"}, "filename": "/tmp/tmpfile123", "severity": "medium", "context": null, "original_file": "https://example.com/main.js"}
```

This format makes it easy to pipe the output into other tools for further processing.

## Customization

You can modify the script to adjust its behavior:

- Change the `is_js_file()` function to include or exclude certain file types.
- Modify the `process_jsluice_output()` function to handle additional types of data or to change how URLs and secrets are processed.
- Adjust the `severity_to_int()` function to change the ordering of severity levels.
- Modify the Nuclei command in `run_nuclei()` function to use different templates or options.

## Notes

- This script relies on the JSluice tool and Nuclei for actual URL and secret extraction. Make sure both tools are properly installed and accessible in your system's PATH.
- The script uses aiohttp to fetch content from URLs asynchronously. Ensure you have the necessary permissions and network access to fetch the content.
- Be cautious when processing JavaScript from untrusted sources.
- The Nuclei integration is specifically set up to use the credential exposure template. You can modify this in the script if you want to use different templates.

## Troubleshooting

If you encounter any issues:

1. Ensure JSluice and Nuclei are correctly installed and accessible from the command line.
2. Check that you have permission to access the URLs you're trying to process.
3. Verify that the input URLs are correctly formatted.
4. If you're having issues with Nuclei, try running it manually on a file to ensure it's working correctly.

## Contributing

Contributions to improve the script are welcome. Please submit a pull request or open an issue to discuss proposed changes.

## Disclaimer

This tool is for educational and ethical testing purposes only. Always ensure you have permission to scan and analyze websites or JavaScript files that you do not own or have explicit permission to test.
