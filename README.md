# gofuzz.py

gofuzz.py is a powerful tool that recursively processes JavaScript files to extract URLs and secrets using the jsluice command-line utility. It starts with an initial URL, processes all JavaScript files it encounters, and outputs a comprehensive list of unique URLs and any secrets found, sorted by severity.

## Features

- Recursively processes JavaScript files
- Extracts URLs from various JavaScript contexts
- Detects secrets (API keys, tokens, etc.) in JavaScript files
- Resolves relative URLs to absolute URLs
- Outputs unique URLs and secrets without headers
- Allows specifying whether to hunt for endpoints, secrets, or both
- Sorts secrets by severity (highest to lowest)
- Removes duplicate secrets
- Includes information about the original JS file where each secret was found

## Prerequisites

- Python 3.6+
- jsluice command-line tool
- curl

## Installation

1. Ensure you have Python 3.6+ installed on your system.
2. Install the jsluice command-line tool. (Refer to the jsluice documentation for installation instructions)
3. Download the `gofuzz.py` script.
4. Make the script executable:

   ```
   chmod +x gofuzz.py
   ```

## Usage

You can use the script in two ways:

1. Process a single URL:

   ```
   echo "https://example.com/script.js" | ./gofuzz.py [options]
   ```

2. Process multiple URLs from a file:

   ```
   cat js_urls.txt | ./gofuzz.py [options]
   ```

### Options

- `-m {endpoints,secrets,both}`, `--mode {endpoints,secrets,both}`: Specify what to hunt for: endpoints, secrets, or both (default: both)

Examples:

- To hunt for endpoints only:
  ```
  echo "https://example.com/script.js" | ./gofuzz.py -m endpoints
  ```

- To hunt for secrets only:
  ```
  echo "https://example.com/script.js" | ./gofuzz.py -m secrets
  ```

- To hunt for both (default behavior):
  ```
  echo "https://example.com/script.js" | ./gofuzz.py -m both
  ```

## Output

The script outputs directly to stdout without headers:

1. When hunting for endpoints (or both), it outputs a sorted list of unique URLs, one per line.
2. When hunting for secrets (or both), it outputs JSON objects representing the secrets, one per line. Secrets are sorted by severity (highest to lowest) and duplicates are removed.

Example output for secrets:

```
{"kind": "AWSAccessKey", "data": {"key": "AKIAIOSFODNN7EXAMPLE", "secret": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"}, "filename": "https://example.com/config.js", "severity": "high", "context": {"awsRegion": "us-west-2", "bucketName": "example-uploads"}, "original_file": "https://example.com/main.js"}
{"kind": "APIKey", "data": {"name": "GOOGLE_MAPS_API_KEY", "value": "AIzaSyC3xbj4UeWLQ2I5lxZpJFkfLwkbhcheQ4E"}, "filename": "https://example.com/main.js", "severity": "medium", "context": {"apiKey": "AIzaSyC3xbj4UeWLQ2I5lxZpJFkfLwkbhcheQ4E"}, "original_file": "https://example.com/main.js"}
```

This format makes it easy to pipe the output into other tools for further processing.

## Customization

You can modify the script to adjust its behavior:

- Change the `is_js_file()` function to include or exclude certain file types.
- Modify the `process_jsluice_output()` function to handle additional types of data or to change how URLs and secrets are processed.
- Adjust the `severity_to_int()` function to change the ordering of severity levels.

## Notes

- This script relies on the jsluice tool for actual URL and secret extraction. Make sure jsluice is properly installed and accessible in your system's PATH.
- The script uses curl to fetch content from URLs. Ensure you have the necessary permissions and network access to fetch the content.
- Be cautious when processing JavaScript from untrusted sources.

## Troubleshooting

If you encounter any issues:

1. Ensure jsluice is correctly installed and accessible from the command line.
2. Check that you have permission to execute curl and access the URLs you're trying to process.
3. Verify that the input URLs are correctly formatted.

## Contributing

Contributions to improve the script are welcome. Please submit a pull request or open an issue to discuss proposed changes.

## Disclaimer

This tool is for educational and ethical testing purposes only. Always ensure you have permission to scan and analyze websites or JavaScript files that you do not own or have explicit permission to test.
