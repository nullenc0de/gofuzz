package fuzzer

import (
	"fmt"
	"os"
	"strings"
	"sync"

	"github.com/nullenc0de/GoFuzz/internal/jsluice"
)

func GenerateFuzzedURLs(inputs []jsluice.JSluiceOutput, concurrent int) ([]string, error) {
	results := make(chan string)
	var wg sync.WaitGroup

	for i := 0; i < concurrent; i++ {
		wg.Add(1)
		go worker(inputs, results, &wg)
	}

	go func() {
		wg.Wait()
		close(results)
	}()

	var fuzzedURLs []string
	for url := range results {
		fuzzedURLs = append(fuzzedURLs, url)
	}

	return fuzzedURLs, nil
}

func worker(inputs []jsluice.JSluiceOutput, results chan<- string, wg *sync.WaitGroup) {
	defer wg.Done()
	for _, input := range inputs {
		fuzzedURLs := generateFuzzedURLsForInput(input)
		for _, url := range fuzzedURLs {
			results <- url
		}
	}
}

func generateFuzzedURLsForInput(input jsluice.JSluiceOutput) []string {
	var fuzzedURLs []string

	baseURL := input.URL
	if strings.Contains(baseURL, "?") {
		baseURL = strings.Split(baseURL, "?")[0]
	}

	fuzzedURLs = append(fuzzedURLs, baseURL)

	for _, param := range input.QueryParams {
		fuzzedURLs = append(fuzzedURLs, fmt.Sprintf("%s?%s=FUZZ", baseURL, param))
	}

	if len(input.QueryParams) > 0 {
		allParams := strings.Join(input.QueryParams, "=FUZZ&") + "=FUZZ"
		fuzzedURLs = append(fuzzedURLs, fmt.Sprintf("%s?%s", baseURL, allParams))
	}

	if input.Method == "POST" || input.Method == "PUT" {
		for _, param := range input.BodyParams {
			fuzzedURLs = append(fuzzedURLs, fmt.Sprintf("%s|%s=FUZZ", baseURL, param))
		}
		if len(input.BodyParams) > 0 {
			allParams := strings.Join(input.BodyParams, "=FUZZ&") + "=FUZZ"
			fuzzedURLs = append(fuzzedURLs, fmt.Sprintf("%s|%s", baseURL, allParams))
		}
	}

	parts := strings.Split(baseURL, "/")
	for i := range parts {
		if i > 2 {
			newParts := append([]string{}, parts[:i]...)
			newParts = append(newParts, "FUZZ")
			newParts = append(newParts, parts[i+1:]...)
			fuzzedURLs = append(fuzzedURLs, strings.Join(newParts, "/"))
		}
	}

	return fuzzedURLs
}

func WriteToFile(urls []string, filename string) error {
	file, err := os.Create(filename)
	if err != nil {
		return err
	}
	defer file.Close()

	for _, url := range urls {
		_, err := file.WriteString(url + "\n")
		if err != nil {
			return err
		}
	}

	return nil
}
