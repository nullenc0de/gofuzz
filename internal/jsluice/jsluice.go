package jsluice

import (
	"encoding/json"
	"os/exec"
)

type JSluiceOutput struct {
	URL         string            `json:"url"`
	QueryParams []string          `json:"queryParams"`
	BodyParams  []string          `json:"bodyParams"`
	Method      string            `json:"method"`
	Headers     map[string]string `json:"headers"`
	Type        string            `json:"type"`
}

func Run(inputFile string) ([]JSluiceOutput, error) {
	cmd := exec.Command("jsluice", "urls", inputFile)
	output, err := cmd.Output()
	if err != nil {
		return nil, err
	}

	var results []JSluiceOutput
	err = json.Unmarshal(output, &results)
	if err != nil {
		return nil, err
	}

	return results, nil
}
