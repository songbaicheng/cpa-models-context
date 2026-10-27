Add Model Context Windows plugin (`models-context`) to the registry

## Plugin

- **Repository**: https://github.com/songbaicheng/cpa-models-context
- **Latest release tag**: `v1.1.1`
- **Logo**: https://raw.githubusercontent.com/songbaicheng/cpa-models-context/main/assets/logo.svg
- **License**: MIT, no third-party Go dependencies
- **Docs**: English [`README.md`](https://github.com/songbaicheng/cpa-models-context/blob/main/README.md) · 简体中文 [`README.zh-CN.md`](https://github.com/songbaicheng/cpa-models-context/blob/main/README.zh-CN.md)

<img src="https://raw.githubusercontent.com/songbaicheng/cpa-models-context/main/assets/logo.svg" width="96" height="96" alt="Model Context Windows logo">

## Capability added

A C ABI v1 **response-interceptor** plugin (`capabilities: response_intercept_after`)
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

## Evidence that the release assets exist

Latest release `v1.1.1`, published by the repository's own tag-triggered workflow:

```
checksums.txt                              103 B
models-context_1.1.1_linux_amd64.zip   1,767,026 B
```

I re-implemented the installer's validation chain from `internal/pluginstore` and ran it
against the live release ([`scripts/check-registry-entry.py`](https://github.com/songbaicheng/cpa-models-context/blob/main/scripts/check-registry-entry.py)):

```
[1/6] registry entry valid: models-context (songbaicheng/cpa-models-context)
[2/6] latest release: version=1.1.1
[3/6] assets present: models-context_1.1.1_linux_amd64.zip, checksums.txt
[4/6] sha256 verified: a3cfe527f309b8ca… (1767026 bytes)
[5/6] zip layout ok: models-context.so (3222000 bytes, ELF64 x86-64)
[6/6] logo ok: SVG (1468 bytes)

OK — models-context v1.1.1 is installable via the plugin store.
```

That covers: `ArchiveName()` asset matching, sha256 against `checksums.txt`, exactly one
dynamic library at the zip root named `models-context.so`, and an ELF64 x86-64 header
probe. The archive was downloaded from the published release, not from a local build.

## Platform coverage

`linux/amd64` only for now. Some registry entries already ship a single platform
(`cpa-apply-patch`, `opencode-go-pool`, `cpa-session-archive`, `cliproxyapi-copilot`), but
if a specific platform matrix is expected for new entries, tell me which ones and I will
publish them before this is merged.

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

## CI on the plugin repository

`gofmt` check, `go test ./...`, `go vet ./...`, `sh build.sh`, Python integration tests,
and a C ABI harness all green on Go 1.26.x / linux-amd64. A tag push whose name does not
match `pluginVersion` fails the release workflow, so assets cannot silently drift from
the declared version.
