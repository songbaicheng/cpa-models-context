# Changelog

## 1.1.0 — Unreleased

- Require every list entry to be a model descriptor; skip non-2xx responses.
- Preserve unknown top-level fields and JSON integer precision when rewriting.
- Clear stale mappings after malformed or absent lifecycle configuration.
- Remove response-exposing diagnostic probe and dormant diagnostic markers.
- Validate ABI version, null arguments, and request-size conversion boundaries.
- Keep positive upstream context values; reject fractional/overflowing config counts.
- Add Go regressions, offline C ABI fixtures, portable foreground build, CI,
  bilingual documentation and upstream attribution.

## 1.0.6 — Internal predecessor

Baseline model-context injection and lifecycle configuration key compatibility.
Not a previously published public release; isolated host validation of this
baseline does not imply validation of 1.1.0.
