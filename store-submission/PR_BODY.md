Add Model Context Windows plugin (`models-context`)

## Plugin

- **Repository**: https://github.com/songbaicheng/cpa-models-context
- **Latest release tag**: `v1.1.1`
- **Logo**: https://raw.githubusercontent.com/songbaicheng/cpa-models-context/main/assets/logo.svg
- **License**: MIT, no third-party Go dependencies
- **Docs**: English [`README.md`](https://github.com/songbaicheng/cpa-models-context/blob/main/README.md) · 简体中文 [`README.zh-CN.md`](https://github.com/songbaicheng/cpa-models-context/blob/main/README.zh-CN.md)

<img src="https://raw.githubusercontent.com/songbaicheng/cpa-models-context/main/assets/logo.svg" width="96" height="96" alt="Model Context Windows logo">

## Capability added

A C ABI v1 **response-interceptor** plugin (`capabilities: response_interceptor`)
that appends operator-configured `context_length` values to OpenAI-shaped
`GET /v1/models` responses, so clients that size their context budget from the model
list get the real window instead of a missing field:

```json
{"id":"example-small","object":"model","context_length":32768}
```

Scope, deliberately narrow:

- `context_length` comes from **operator config**; the plugin does not discover or
  measure model capacity.
- It does **not** enforce, clamp, or validate token limits.
- It does **not** modify inference requests, responses, or streaming bodies — only the
  model-list payload is rewritten (unknown top-level fields and JSON integer precision
  are preserved).

## Evidence that the required assets exist

Release `v1.1.1` ships both Linux architectures with a checksum file:

```
checksums.txt                                206 B
models-context_1.1.1_linux_amd64.zip   1,767,022 B
models-context_1.1.1_linux_arm64.zip   1,618,690 B
```

I re-implemented the installer's validation chain from `internal/pluginstore` and ran it
against the live release ([`scripts/check-registry-entry.py`](https://github.com/songbaicheng/cpa-models-context/blob/main/scripts/check-registry-entry.py)):

```
[1/6] registry entry valid: models-context (songbaicheng/cpa-models-context)
[2/6] latest release: version=1.1.1
[3/6] assets present: models-context_1.1.1_linux_amd64.zip,
      models-context_1.1.1_linux_arm64.zip, checksums.txt
[4/6] models-context_1.1.1_linux_amd64.zip: sha256 d3ccd742bcdd31cd… OK (1767022 bytes)
[4/6] models-context_1.1.1_linux_arm64.zip: sha256 e885897be6cad3a3… OK (1618690 bytes)
[5/6] zip layout ok: ..._linux_amd64.zip -> models-context.so (3222000 bytes, ELF64 x86-64)
[5/6] zip layout ok: ..._linux_arm64.zip -> models-context.so (3053984 bytes, ELF64 aarch64)
[6/6] logo ok: SVG (1468 bytes)

OK — models-context v1.1.1 is installable via the plugin store.
```

That covers `ArchiveName()` asset matching (with `id` = `models-context`, so
`models-context_<version>_linux_<arch>.zip`), sha256 against `checksums.txt`, exactly one
dynamic library at the zip root named `models-context.so`, and the ELF machine type
matching each archive's claimed architecture. Archives were downloaded from the published
release, not from a local build.

Runtime checks actually performed:

- **linux/amd64**: loaded and registered in an isolated CLIProxyAPI `v8.0.44` host
  (`plugin registered plugin_id=models-context ... version=1.1.1`), and in a `v8.0.23`
  host where a fictional provider's `/v1/models` returned the configured
  `context_length: 32768`. The shipped `.so` requires at most `GLIBC_2.34`; the hosts run
  glibc 2.39.
- **linux/arm64**: all four ABI symbols (`cliproxy_plugin_init`, `cliproxyPluginCall`,
  `cliproxyPluginFree`, `cliproxyPluginShutdown`) resolve via `dlopen`/`dlsym` on real
  aarch64 hardware (glibc 2.39, requires ≤ `GLIBC_2.34`). No arm64 CLIProxyAPI host was
  available to load it end to end, and the README says so rather than implying otherwise.

## Platform coverage

Linux amd64 + Linux arm64. No macOS or Windows build: a C ABI plugin is only loadable by
the host that matches it, and macOS/Windows CLIProxyAPI hosts are not what this targets.
macOS users can build from source (documented in the README). If a wider matrix is
required for registry entries, tell me which targets and I will add them before merge.

## Registry diff

`registry.json` only — one entry appended at the end of the array, 12 added lines, no
other entries touched and no reformatting of neighbours:

```json
{
  "id": "models-context",
  "name": "Model Context Windows",
  "description": "Adds operator-configured context_length values to OpenAI-shaped /v1/models responses, so the model list reports the real context window instead of omitting it. A C ABI v1 response-interceptor plugin: it does not discover or measure capacities, does not enforce or clamp token limits, and does not touch inference requests — it only rewrites the model list payload. | 为 OpenAI 形状的 /v1/models 模型列表补上管理员配置的 context_length，让客户端能读到真实上下文窗口，而不是拿到一个缺字段的模型列表。C ABI v1 响应拦截插件：不探测、不测量模型容量，不强制或裁剪 token 上限，也不修改任何推理请求——只重写模型列表响应。",
  "author": "songbaicheng",
  "version": "1.1.1",
  "repository": "https://github.com/songbaicheng/cpa-models-context",
  "logo": "https://raw.githubusercontent.com/songbaicheng/cpa-models-context/main/assets/logo.svg",
  "homepage": "https://github.com/songbaicheng/cpa-models-context",
  "license": "MIT",
  "tags": ["Models", "Metadata", "Context"]
}
```

`id` passes `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, `version` has no `v` prefix,
`repository` is exactly `https://github.com/{owner}/{repo}`, and ids are unique
(149 → 150).

## CI

On the plugin repository: `gofmt` check, `go test ./...`, `go vet ./...`, `sh build.sh`,
Python integration tests, a C ABI harness, plus a matrix job that compiles the shared
library natively on `linux/amd64` and `linux/arm64`. A tag push whose name does not match
`pluginVersion` fails the release workflow, so the published assets cannot silently drift
from the declared version.
