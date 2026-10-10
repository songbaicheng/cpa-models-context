package main

import (
	"encoding/json"
	"testing"
)

func configure(t *testing.T, text string) {
	t.Helper()
	raw, err := json.Marshal(map[string]any{"config_yaml": []byte(text), "schema_version": 1})
	if err != nil {
		t.Fatal(err)
	}
	reloadConfig(raw)
}
func interceptBody(t *testing.T, body string, extra map[string]any) map[string]json.RawMessage {
	t.Helper()
	req := map[string]any{"Body": []byte(body), "StatusCode": 200}
	for k, v := range extra {
		req[k] = v
	}
	raw, _ := json.Marshal(req)
	out, err := interceptAfter(raw)
	if err != nil {
		t.Fatal(err)
	}
	var env struct {
		OK     bool
		Result struct{ Body []byte }
	}
	if err := json.Unmarshal(out, &env); err != nil {
		t.Fatal(err)
	}
	if !env.OK {
		t.Fatal(string(out))
	}
	if len(env.Result.Body) == 0 {
		return nil
	}
	var result map[string]json.RawMessage
	if err := json.Unmarshal(env.Result.Body, &result); err != nil {
		t.Fatal(err)
	}
	return result
}
func TestRejectNonModelLists(t *testing.T) {
	configure(t, "context_lengths:\n  example-small: 4096\n")
	for _, body := range []string{
		`{"object":"list","data":[{"id":"example-small","object":"file"}]}`,
		`{"object":"list","data":[{"id":"example-small"}]}`,
		`{"object":"other","data":[{"id":"example-small","object":"model"}]}`,
		`{"data":[{"id":"example-small","object":null}]}`,
		`{"object":"list","data":[{"id":"example-small","object":"model"},null]}`,
		`{"object":"list","data":[]}`, `null`, `not json`,
	} {
		if interceptBody(t, body, nil) != nil {
			t.Errorf("rewrote %s", body)
		}
	}
}
func TestPreserveUnknownFields(t *testing.T) {
	configure(t, "context_lengths:\n  example-small: 4096\n")
	body := `{"object":"list","cursor":{"large":9007199254740993},"data":[{"id":"example-small","object":"model","large":9007199254740993}]}`
	out := interceptBody(t, body, nil)
	if out == nil {
		t.Fatal("no rewrite")
	}
	if string(out["cursor"]) != `{"large":9007199254740993}` {
		t.Fatalf("lost cursor: %s", out["cursor"])
	}
	var entries []map[string]json.RawMessage
	json.Unmarshal(out["data"], &entries)
	if string(entries[0]["large"]) != "9007199254740993" {
		t.Fatal("lost integer precision")
	}
	if string(entries[0]["context_length"]) != "4096" {
		t.Fatal("missing injection")
	}
}
func TestInvalidConfigClearsStaleState(t *testing.T) {
	for _, raw := range []string{`{`, `{}`, `{"config_yaml":123}`, `{"config_yaml":"invalid base64!"}`, `null`} {
		configure(t, "context_lengths:\n  example-small: 4096\n")
		reloadConfig([]byte(raw))
		if contextCount() != 0 {
			t.Errorf("stale config after %s", raw)
		}
	}
}
func TestProbeCannotExposeResponse(t *testing.T) {
	configure(t, "probe: true\ncontext_lengths:\n  example-small: 4096\n")
	out, err := handleMethod("response.intercept_after", []byte(`{"Model":"example-small","Body":"c2VjcmV0"}`))
	if err != nil {
		t.Fatal(err)
	}
	if string(out) != `{"ok":true,"result":{}}` {
		t.Fatalf("probe exposure: %s", out)
	}
}
func TestInjectionSemantics(t *testing.T) {
	configure(t, "context_lengths:\n  example-small: 4096\n")
	for _, value := range []string{`42`, `"42"`, `42.5`} {
		body := `{"object":"list","data":[{"id":"example-small","object":"model","context_length":` + value + `}]}`
		if interceptBody(t, body, nil) != nil {
			t.Errorf("overwrote positive upstream %s", value)
		}
	}
	for _, value := range []string{`null`, `0`, `-1`, `"invalid"`} {
		body := `{"data":[{"id":"example-small","object":"model","context_length":` + value + `}]}`
		if interceptBody(t, body, nil) == nil {
			t.Errorf("did not repair %s", value)
		}
	}
	body := `{"object":"list","data":[{"id":"example-small","object":"model"}]}`
	for _, extra := range []map[string]any{{"Model": "example-small"}, {"RequestedModel": "example-small"}, {"Stream": true}, {"StatusCode": 500}} {
		if interceptBody(t, body, extra) != nil {
			t.Errorf("rewrote excluded request %v", extra)
		}
	}
	configure(t, "context_lengths:\n  other-model: 8192\n")
	if interceptBody(t, body, nil) != nil {
		t.Fatal("unknown model rewritten")
	}
}
func TestNestedConfigEntriesRejected(t *testing.T) {
	for _, tc := range []struct {
		text      string
		wantCount int
	}{
		{"context_lengths:\n  invalid:\n    example-small: 4096\n", 0},
		{"context_lengths:\n# ignored comment: 1024\n      # deeper comment: 2048\n  invalid:\n    example-small: 4096\n    context_lengths:\n      nested: 8192\n  valid: 16384\n  '': 32768\n  : 65536\nother: true\n", 1},
	} {
		got := parseContextLengths(tc.text)
		if tc.wantCount == 1 && got["valid"] != 16384 {
			t.Errorf("lost direct scalar entry: %v", got)
		}
		if len(got) != tc.wantCount {
			t.Errorf("accepted nested, comment, or empty-ID entries from %q: %v", tc.text, got)
		}
	}
}

func TestConfigScalarComments(t *testing.T) {
	got := parseContextLengths("context_lengths:\n  plain: 4096 # tokens\n  single: '8192' # tokens\n  double: \"16384\" # tokens\n")
	want := map[string]int{"plain": 4096, "single": 8192, "double": 16384}
	if len(got) != len(want) {
		t.Fatalf("parsed %v, want %v", got, want)
	}
	for name, number := range want {
		if got[name] != number {
			t.Errorf("%s: got %d, want %d", name, got[name], number)
		}
	}
}

func TestConfigForms(t *testing.T) {
	for _, text := range []string{
		"context_lengths:\n  example-small: 4096\n  'example:large': '8192'\n",
		"context_lengths: '{\"example-small\":4096,\"example:large\":8192}'\n",
		"context_lengths_json: '{\"example-small\":4096,\"example:large\":8192}'\n",
	} {
		configure(t, text)
		if contextCount() != 2 {
			t.Fatalf("parsed %d entries from %s", contextCount(), text)
		}
	}
	configure(t, "context_lengths: '{\"fractional\":1.5,\"huge\":1e100,\"empty\":0,\"suffix\":\"1M\"}'\n")
	if contextCount() != 0 {
		t.Fatal("accepted invalid token counts")
	}
}
