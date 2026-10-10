// models-context adds configured context-window token counts to model lists.
// Requires the CLIProxyAPI C ABI v1 response-interceptor protocol.
package main

/*
#include <stdint.h>
#include <stdlib.h>

typedef struct {
	void* ptr;
	size_t len;
} cliproxy_buffer;

typedef int (*cliproxy_host_call_fn)(void*, const char*, const uint8_t*, size_t, cliproxy_buffer*);
typedef void (*cliproxy_host_free_fn)(void*, size_t);

typedef struct {
	uint32_t abi_version;
	void* host_ctx;
	cliproxy_host_call_fn call;
	cliproxy_host_free_fn free_buffer;
} cliproxy_host_api;

typedef int (*cliproxy_plugin_call_fn)(char*, uint8_t*, size_t, cliproxy_buffer*);
typedef void (*cliproxy_plugin_free_fn)(void*, size_t);
typedef void (*cliproxy_plugin_shutdown_fn)(void);

typedef struct {
	uint32_t abi_version;
	cliproxy_plugin_call_fn call;
	cliproxy_plugin_free_fn free_buffer;
	cliproxy_plugin_shutdown_fn shutdown;
} cliproxy_plugin_api;

extern int cliproxyPluginCall(char*, uint8_t*, size_t, cliproxy_buffer*);
extern void cliproxyPluginFree(void*, size_t);
extern void cliproxyPluginShutdown(void);

static const cliproxy_host_api* stored_host;

static void store_host_api(const cliproxy_host_api* host) {
	stored_host = host;
}
*/
import "C"

import (
	"bytes"
	"encoding/json"
	"math"
	"strconv"
	"strings"
	"sync"
	"unsafe"
)

const (
	abiVersion uint32 = 1
	// pluginVersion is included in registration metadata and artifact names.
	// Installation/discovery and reload behavior depend on the host version.
	// Publish changed binaries under a new version and follow the host's
	// documented upgrade procedure; do not rely on replacing a loaded file.
	pluginVersion = "1.1.0"
)

// ── JSON envelope shared with the host ──────────────────────────────────────

type envelope struct {
	OK     bool            `json:"ok"`
	Result json.RawMessage `json:"result,omitempty"`
	Error  *envelopeError  `json:"error,omitempty"`
}

type envelopeError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

// ── runtime state ───────────────────────────────────────────────────────────

var (
	cfgMu      sync.RWMutex
	ctxLens    = map[string]int{} // model id -> context window
	configSeen bool               // a non-empty ConfigYAML was delivered
)

func main() {}

//export cliproxy_plugin_init
func cliproxy_plugin_init(host *C.cliproxy_host_api, plugin *C.cliproxy_plugin_api) C.int {
	if plugin == nil || host == nil || uint32(host.abi_version) != abiVersion {
		return 1
	}
	C.store_host_api(host)
	plugin.abi_version = C.uint32_t(abiVersion)
	plugin.call = C.cliproxy_plugin_call_fn(C.cliproxyPluginCall)
	plugin.free_buffer = C.cliproxy_plugin_free_fn(C.cliproxyPluginFree)
	plugin.shutdown = C.cliproxy_plugin_shutdown_fn(C.cliproxyPluginShutdown)
	return 0
}

//export cliproxyPluginCall
func cliproxyPluginCall(method *C.char, request *C.uint8_t, requestLen C.size_t, response *C.cliproxy_buffer) C.int {
	if response != nil {
		response.ptr = nil
		response.len = 0
	}
	if response == nil {
		return 1
	}
	if (request == nil && requestLen != 0) || uint64(requestLen) > 2147483647 {
		writeResponse(response, errorEnvelope("invalid_request", "invalid request buffer"))
		return 1
	}
	if method == nil {
		writeResponse(response, errorEnvelope("invalid_method", "method is required"))
		return 1
	}
	payload := goBytes(request, requestLen)
	raw, errHandle := handleMethod(C.GoString(method), payload)
	if errHandle != nil {
		writeResponse(response, errorEnvelope("plugin_error", errHandle.Error()))
		return 1
	}
	writeResponse(response, raw)
	return 0
}

//export cliproxyPluginFree
func cliproxyPluginFree(ptr unsafe.Pointer, length C.size_t) {
	if ptr != nil {
		C.free(ptr)
	}
	_ = length
}

//export cliproxyPluginShutdown
func cliproxyPluginShutdown() {}

// ── method dispatch ─────────────────────────────────────────────────────────

func handleMethod(method string, request []byte) ([]byte, error) {
	switch method {
	case "plugin.register", "plugin.reconfigure":
		reloadConfig(request)
		return registrationEnvelope()
	case "response.intercept_after":
		return interceptAfter(request)
	case "response.intercept_before":
		// Not requested through capabilities; answer with a no-op.
		return okRaw(`{}`)
	case "plugin.quiesce":
		// The host asks plugins to quiesce around a hot reload. Answering with
		// a no-op keeps this plugin's log free of "unsupported" noise.
		return okRaw(`{}`)
	default:
		return errorEnvelope("unknown_method", "unknown method: "+method), nil
	}
}

// registrationEnvelope declares exactly one capability: the response
// interceptor. Declaring nothing else keeps the plugin inert for every other
// CPA code path.
// pluginName is the clean, user-facing name shown in the management panel and
// the CPA log. Diagnostic markers are appended only when configuration is
// unhealthy, so a working deployment never leaks internal counters into the UI.
const pluginName = "Model Context Windows"

func registrationEnvelope() ([]byte, error) {
	meta := `"metadata":{` +
		`"Name":"` + pluginDisplayName() + `",` +
		`"Version":"` + pluginVersion + `",` +
		`"Author":"songbaicheng",` +
		`"GitHubRepository":"https://github.com/songbaicheng/cpa-models-context",` +
		// ConfigFields drives the management panel's settings form. Type MUST
		// match the configured value's real shape: context_lengths is an object
		// (model id -> token count), and declaring it "string" made the panel
		// render the raw object as "[object Object]".
		`"ConfigFields":[` +
		`{"Name":"context_lengths","Type":"object",` +
		`"Description":"Exact model ID to positive integer context-window token count. Example: example-small: 32768."}` +
		`]}`
	caps := `"capabilities":{"response_interceptor":true}`
	n := contextCount()
	return okRaw(`{"schema_version":1,` + meta + `,` + caps + `,"context_lengths_loaded":` + strconv.Itoa(n) + `}`)
}

// pluginDisplayName returns the clean name while configuration is healthy and
// appends a diagnostic marker only when it is not. The CPA log and the
// management panel share this string, so the healthy case stays readable.
func pluginDisplayName() string {
	cfgMu.RLock()
	seen := configSeen
	n := len(ctxLens)
	cfgMu.RUnlock()
	if !seen {
		return pluginName + " (configuration unavailable)"
	}
	if n == 0 {
		return pluginName + " (empty mapping)"
	}
	return pluginName
}

func contextCount() int {
	cfgMu.RLock()
	defer cfgMu.RUnlock()
	return len(ctxLens)
}

// ── /v1/models interception ─────────────────────────────────────────────────

type interceptRequest struct {
	RequestID       string
	SourceFormat    string
	Model           string
	RequestedModel  string
	Stream          bool
	RequestBody     []byte
	Body            []byte
	StatusCode      int
	ResponseHeaders map[string][]string
}

type modelList struct {
	Object string           `json:"object"`
	Data   []map[string]any `json:"data"`
}

func interceptAfter(request []byte) ([]byte, error) {
	var req interceptRequest
	if err := json.Unmarshal(request, &req); err != nil {
		// Never break the response path on a parse failure.
		return okRaw(`{}`)
	}

	// A model-execution response always carries the model id; the model list
	// does not. Combined with the body shape check below this makes an
	// accidental rewrite of a chat completion impossible.
	if strings.TrimSpace(req.Model) != "" || strings.TrimSpace(req.RequestedModel) != "" || req.Stream {
		return okRaw(`{}`)
	}
	if len(req.Body) == 0 || req.StatusCode < 200 || req.StatusCode >= 300 {
		return okRaw(`{}`)
	}

	var list modelList
	decoder := json.NewDecoder(bytes.NewReader(req.Body))
	decoder.UseNumber()
	if err := decoder.Decode(&list); err != nil {
		return okRaw(`{}`)
	}
	var original map[string]json.RawMessage
	if err := json.Unmarshal(req.Body, &original); err != nil {
		return okRaw(`{}`)
	}
	if (list.Object != "" && list.Object != "list") || !looksLikeModelList(list) {
		return okRaw(`{}`)
	}

	cfgMu.RLock()
	changed := 0
	for _, entry := range list.Data {
		id, _ := entry["id"].(string)
		if id == "" {
			continue
		}
		want, ok := ctxLens[id]
		if !ok {
			continue
		}
		// Never overwrite a value the upstream already advertised.
		if existing, has := entry["context_length"]; has {
			if positiveNumber(existing) {
				continue
			}
		}
		entry["context_length"] = want
		changed++
	}
	cfgMu.RUnlock()

	if changed == 0 {
		return okRaw(`{}`)
	}

	data, err := json.Marshal(list.Data)
	if err != nil {
		return okRaw(`{}`)
	}
	original["data"] = data
	body, err := json.Marshal(original)
	if err != nil {
		return okRaw(`{}`)
	}
	out, err := json.Marshal(map[string]any{"Body": body})
	if err != nil {
		return okRaw(`{}`)
	}
	return okRaw(string(out))
}

// looksLikeModelList is a defensive secondary check: an OpenAI model list is
// `{"object":"list","data":[{"object":"model",...}]}`. Some gateways omit the
// top-level object field, so accept a data array whose entries all look like
// model descriptors.
func looksLikeModelList(list modelList) bool {
	if len(list.Data) == 0 {
		return false
	}
	for _, entry := range list.Data {
		if id, ok := entry["id"].(string); !ok || strings.TrimSpace(id) == "" {
			return false
		}
		if obj, ok := entry["object"].(string); !ok || obj != "model" {
			return false
		}
	}
	return true
}

// positiveNumber preserves finite positive upstream numbers, including numeric strings.
func positiveNumber(v any) bool {
	var text string
	switch n := v.(type) {
	case json.Number:
		text = string(n)
	case string:
		text = strings.TrimSpace(n)
	default:
		return false
	}
	n, err := strconv.ParseFloat(text, 64)
	return err == nil && n > 0 && !math.IsInf(n, 0) && !math.IsNaN(n)
}

func toInt(v any) (int, bool) {
	switch n := v.(type) {
	case float64:
		i, err := strconv.Atoi(strconv.FormatFloat(n, 'f', -1, 64))
		return i, err == nil
	case int:
		return n, true
	case json.Number:
		i, err := strconv.Atoi(string(n))
		return i, err == nil
	case string:
		i, err := strconv.Atoi(strings.TrimSpace(n))
		return i, err == nil
	}
	return 0, false
}

// ── config parsing ──────────────────────────────────────────────────────────

// registerRequest is the payload of plugin.register / plugin.reconfigure.
//
// CPA marshals its rpcLifecycleRequest with snake_case json tags
// (config_yaml / schema_version). Plain Go field-name matching therefore
// silently yields an empty config: "config_yaml" != "ConfigYAML". Accept both
// spellings so a future CPA rename cannot silently empty the config again.
type registerRequest struct {
	ConfigYAML    []byte
	SchemaVersion int
}

func (r *registerRequest) UnmarshalJSON(data []byte) error {
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}
	decodeBytes := func(keys ...string) []byte {
		for _, key := range keys {
			payload, ok := raw[key]
			if !ok {
				continue
			}
			var decoded []byte
			if err := json.Unmarshal(payload, &decoded); err == nil {
				return decoded
			}
		}
		return nil
	}
	decodeInt := func(keys ...string) int {
		for _, key := range keys {
			payload, ok := raw[key]
			if !ok {
				continue
			}
			var decoded int
			if err := json.Unmarshal(payload, &decoded); err == nil {
				return decoded
			}
		}
		return 0
	}
	r.ConfigYAML = decodeBytes("config_yaml", "ConfigYAML", "configYAML", "ConfigYaml")
	r.SchemaVersion = decodeInt("schema_version", "SchemaVersion")
	return nil
}

func reloadConfig(request []byte) {
	var reg registerRequest
	if err := json.Unmarshal(request, &reg); err != nil || len(reg.ConfigYAML) == 0 {
		// Record the failure so the host log (via the reported plugin name)
		// shows a config that never arrived, instead of a silent zero.
		cfgMu.Lock()
		configSeen = false
		ctxLens = map[string]int{}
		cfgMu.Unlock()
		return
	}
	text := string(reg.ConfigYAML)
	parsed := parseContextLengths(text)
	cfgMu.Lock()
	ctxLens = parsed
	configSeen = true
	cfgMu.Unlock()
}

// parseContextLengths extracts the `context_lengths` mapping out of the
// plugin's own config block. CPA hands the plugin `plugins.configs.<id>` as
// normalized YAML; we deliberately avoid a YAML dependency (the plugin builds
// with the standard library only) and instead understand the two shapes that
// block can take:
//
//	context_lengths:            context_lengths: '{"a":1,"b":2}'
//	    a: 1
//	    b: 2
func parseContextLengths(text string) map[string]int {
	out := map[string]int{}
	lines := strings.Split(text, "\n")
	const keyBlock = "context_lengths"
	const keyInline = "context_lengths_json"

	for i := 0; i < len(lines); i++ {
		raw := strings.TrimRight(lines[i], "\r")
		if strings.TrimSpace(raw) == "" {
			continue
		}

		// Inline JSON form: context_lengths: '{"m":123}' (also accepts [key::] prefix)
		if idx := indexKey(raw, keyInline); idx >= 0 {
			val := strings.TrimSpace(raw[idx+len(keyInline):])
			val = strings.TrimPrefix(val, ":")
			val = strings.TrimSpace(val)
			mergeInlineJSON(val, out)
			continue
		}

		idx := indexKey(raw, keyBlock)
		if idx < 0 {
			continue
		}
		after := raw[idx+len(keyBlock):]
		colon := strings.Index(after, ":")
		if colon < 0 {
			continue
		}
		valuePart := strings.TrimSpace(after[colon+1:])
		if valuePart != "" {
			// Inline form: either a JSON object or nothing usable.
			mergeInlineJSON(valuePart, out)
			continue
		}

		// Block form: only direct children of the mapping are scalar entries.
		parentIndent := len(raw) - len(strings.TrimLeft(raw, " 	"))
		childIndent := -1
		for j := i + 1; j < len(lines); j++ {
			child := strings.TrimRight(lines[j], "\r")
			entry := strings.TrimSpace(child)
			if entry == "" || strings.HasPrefix(entry, "#") {
				i = j
				continue
			}
			indent := len(child) - len(strings.TrimLeft(child, " 	"))
			if indent <= parentIndent {
				i = j - 1
				break
			}
			// Consume descendants so the outer loop cannot rescan nested keys.
			i = j
			if childIndent < 0 {
				childIndent = indent
			}
			if indent != childIndent {
				continue
			}
			name, number, ok := splitMappingEntry(entry)
			if ok {
				out[name] = number
			}
		}
	}
	return out
}

// indexKey finds `key` at the start of a YAML line (after optional indentation
// and an optional leading `- ` for list items).
func indexKey(line, key string) int {
	trimmed := line
	offset := 0
	for offset < len(trimmed) && (trimmed[offset] == ' ' || trimmed[offset] == '\t') {
		offset++
	}
	if strings.HasPrefix(trimmed[offset:], "- ") {
		offset += 2
	}
	if strings.HasPrefix(trimmed[offset:], key) && len(trimmed[offset:]) > len(key) {
		rest := trimmed[offset+len(key):]
		if strings.HasPrefix(rest, ":") || strings.HasPrefix(rest, " :") {
			return offset
		}
	}
	return -1
}

// splitMappingEntry parses `name: 123`, `"name:with:colons": 123` and
// `name: "123"` into its parts.
func splitMappingEntry(entry string) (string, int, bool) {
	colon := strings.LastIndex(entry, ": ")
	if colon < 0 {
		return "", 0, false
	}
	name := strings.TrimSpace(entry[:colon])
	name = strings.Trim(name, `"'`)
	if strings.TrimSpace(name) == "" || strings.HasPrefix(entry, "#") {
		return "", 0, false
	}
	value := strings.TrimSpace(entry[colon+2:])
	// Drop trailing YAML comments before unquoting scalar integers.
	if hash := strings.Index(value, " #"); hash >= 0 {
		value = strings.TrimSpace(value[:hash])
	}
	value = strings.Trim(value, `"'`)
	n, err := strconv.Atoi(value)
	if err != nil || n <= 0 {
		return "", 0, false
	}
	return name, n, true
}

func mergeInlineJSON(value string, out map[string]int) {
	value = strings.TrimSpace(value)
	value = strings.Trim(value, `"'`)
	if !strings.HasPrefix(value, "{") {
		return
	}
	var m map[string]any
	decoder := json.NewDecoder(strings.NewReader(value))
	decoder.UseNumber()
	if !json.Valid([]byte(value)) || decoder.Decode(&m) != nil {
		return
	}
	for k, v := range m {
		if n, ok := toInt(v); ok && n > 0 {
			out[k] = n
		}
	}
}

// ── envelope helpers ────────────────────────────────────────────────────────

func okRaw(result string) ([]byte, error) {
	return json.Marshal(envelope{OK: true, Result: json.RawMessage(result)})
}

func errorEnvelope(code, message string) []byte {
	raw, _ := json.Marshal(envelope{OK: false, Error: &envelopeError{Code: code, Message: message}})
	return raw
}

func writeResponse(response *C.cliproxy_buffer, raw []byte) {
	if response == nil || len(raw) == 0 {
		return
	}
	ptr := C.CBytes(raw)
	if ptr == nil {
		return
	}
	response.ptr = ptr
	response.len = C.size_t(len(raw))
}

func goBytes(p *C.uint8_t, n C.size_t) []byte {
	if p == nil || n == 0 {
		return nil
	}
	return C.GoBytes(unsafe.Pointer(p), C.int(n))
}
