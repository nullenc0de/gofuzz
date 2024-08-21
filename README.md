# GoFuzz

GoFuzz is a powerful URL fuzzing tool written in Go that leverages jsluice for advanced parsing. It generates a variety of fuzzed URLs based on the structure and parameters of input URLs, making it an invaluable asset for web application security testing and API endpoint discovery.

## Features

- Utilizes jsluice for advanced URL parsing and parameter extraction
- Generates fuzzed URLs for various scenarios:
  - Query parameters
  - Body parameters (for POST and PUT requests)
  - Path parameters
- Concurrent processing for improved performance
- Flexible input/output options (file or stdout)
- Easy integration with other security tools

## Prerequisites

- Go 1.21 or higher
- jsluice (must be installed and available in your PATH)

## Installation

1. Clone the repository:
   ```
   go install github.com/yourusername/GoFuzz/cmd/gofuzz@latest
   OR
   git clone https://github.com/yourusername/GoFuzz.git
   cd GoFuzz
   ```

2. Build the project:
   ```
   go build -o gofuzz cmd/gofuzz/main.go
   ```

3. (Optional) Move the binary to a directory in your PATH:
   ```
   sudo mv gofuzz /usr/local/bin/
   ```

## Usage

Basic usage:

```
gofuzz -input urls.txt -output fuzzed_urls.txt -concurrent 20
```

Options:
- `-input`: Input file containing URLs (required)
- `-output`: Output file for fuzzed URLs (optional, defaults to stdout)
- `-concurrent`: Number of concurrent workers (optional, defaults to 10)

## Example

Input file (`urls.txt`):
```
https://api.example.com/users?id=123
https://api.example.com/search
https://api.example.com/products/456
```

Running GoFuzz:
```
gofuzz -input urls.txt -output fuzzed_urls.txt
```

Output file (`fuzzed_urls.txt`):
```
https://api.example.com/users
https://api.example.com/users?id=FUZZ
https://api.example.com/FUZZ/users
https://api.example.com/search
https://api.example.com/FUZZ
https://api.example.com/products/456
https://api.example.com/products/FUZZ
https://api.example.com/FUZZ/456
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This tool is for educational and testing purposes only. Always ensure you have permission before testing any systems you do not own or have explicit permission to test.
