# JSluice URL Processor

This tool processes URLs using jsluice and formats them for use in web browsers. It reads URLs from stdin, runs them through jsluice, and outputs processed URLs with merged query parameters.

## Prerequisites

- Python 3.6+
- jsluice - go install github.com/BishopFox/jsluice/cmd/jsluice@latest
- curl

## Installation

1. Clone this repository or download the `process_jsluice.py` script.
2. Make the script executable:

   ```
   chmod +x process_jsluice.py
   ```

## Usage

### Basic Usage

Process a single URL:

```
echo "https://example.com" | ./process_jsluice.py
```

Process multiple URLs from a file:

```
cat urls.txt | ./process_jsluice.py
```

### Integration with other tools

Use with `katana` to crawl a website and process all discovered URLs:

```
katana -u "https://example.com/test.js" | ./process_jsluice.py
```

## Notes

- The script preserves existing query parameter values in the URL.
- It adds new parameters from the jsluice output if they're not already in the URL.
- Encoded characters in URLs are preserved.

## Troubleshooting

If you encounter any issues, make sure:
- jsluice is installed and accessible in your PATH.
- You have necessary permissions to execute the script and run curl commands.
- Your input URLs are properly formatted.

For any bugs or feature requests, please open an issue in the repository.
