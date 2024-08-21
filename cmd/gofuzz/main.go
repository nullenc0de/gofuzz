package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/nullenc0de/GoFuzz/internal/fuzzer"
	"github.com/nullenc0de/GoFuzz/internal/jsluice"
)

func main() {
	inputFile := flag.String("input", "", "Input file containing URLs")
	outputFile := flag.String("output", "", "Output file for formatted URLs")
	concurrent := flag.Int("concurrent", 10, "Number of concurrent workers")
	flag.Parse()

	if *inputFile == "" {
		fmt.Println("Please provide an input file")
		flag.Usage()
		os.Exit(1)
	}

	jsluiceOutput, err := jsluice.Run(*inputFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error running jsluice: %v\n", err)
		os.Exit(1)
	}

	fuzzedURLs, err := fuzzer.GenerateFuzzedURLs(jsluiceOutput, *concurrent)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error generating fuzzed URLs: %v\n", err)
		os.Exit(1)
	}

	if *outputFile != "" {
		err = fuzzer.WriteToFile(fuzzedURLs, *outputFile)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error writing to output file: %v\n", err)
			os.Exit(1)
		}
	} else {
		for _, url := range fuzzedURLs {
			fmt.Println(url)
		}
	}
}
