# Contributing

Keep changes focused, dependency-free, and covered by regression tests. Use
fictional model IDs and sanitized fixtures; never submit credentials, private
response bodies, or deployment details.

Before submitting a pull request (Linux, Go 1.26, cgo toolchain, Python 3):

```sh
gofmt -w main.go main_test.go
go test ./...
go vet ./...
sh build.sh
python3 harness.py dist/models-context-v1.1.0.so
```

Use the version in `main.go` if it changes. Describe exactly which commands and
host versions you tested; offline harness success is not host integration.
Configuration parsing intentionally supports a small normalized subset; do not
claim general YAML support. Keep both READMEs consistent. Bump `pluginVersion`
and update the changelog for released behavior changes. ABI-derived changes must
preserve upstream attribution and be reviewed against an identified source.
