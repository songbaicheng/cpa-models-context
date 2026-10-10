# Verification record

## 2026-10-10 — source version 1.1.0

Environment: Linux amd64, Debian 12/glibc, Go 1.26.5, GCC 12.2.0,
Python 3. Build/test tooling was isolated from the running production host.

Executed successfully:

- `gofmt` on Go source and tests.
- `go test -v ./...`: eight test functions passed.
- `go vet ./...`: exited 0.
- `sh build.sh`: produced the c-shared library.
- `python3 harness.py dist/models-context-v1.1.0.so`: C ABI checks passed.
- The isolated host test (`tests/integration.py`) loaded 1.1.0 into
  CLIProxyAPI v8.0.23, commit `d318bcc`, using only fictional provider data.
  `GET /v1/models` returned HTTP 200 with the entry:

```json
{"id":"example-model","object":"model","owned_by":"example-provider","context_length":32768}
```

Other host-generated fields are omitted above. No inference request was made.
The temporary test container was removed after the test. A deliberately invalid
host image was also tested: startup failed as expected and no test container
remained. This result does not
establish compatibility with untested versions, architectures, libc variants,
providers, or clients, nor the true capacity of any model.

Local verification artifact (not a published release asset):

- File: `models-context-v1.1.0.so`
- Size: 3,211,128 bytes
- SHA-256: `218cd0a1c2ca518ed89cd4e23f601040466120eaa450b468341bf47421c289e6`

The hash identifies this build only. Builds with different compilers, paths,
flags or source changes need not have the same hash. Generated binaries are
excluded from the source repository.
