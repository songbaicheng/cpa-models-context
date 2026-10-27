#!/usr/bin/env python3
"""End-to-end check that a registry entry is installable by CLIProxyAPI.

Reimplements the exact validation chain from CLIProxyAPI's internal/pluginstore
package (registry.go / github.go / install.go) against the *live* GitHub API and
the real release artifact, so a store submission can be verified before opening
a PR instead of after a maintainer rejects it.

Checks, in the order the real installer performs them:
  1. registry decodes and passes ValidateRegistry (id rules, required fields,
     version rules, unique ids, repository shape)
  2. GET /releases/latest resolves and its tag is a valid dotted version
  3. ArchiveName(id, version, goos, goarch) matches a real release asset, and
     checksums.txt is present
  4. the archive downloads and its sha256 matches checksums.txt
  5. the zip holds exactly one dynamic library, at the zip root, named
     <id>.<ext> (or <id>-v<version>.<ext>) — verified by reading the ELF header
  6. the logo URL (if any) returns 200 with image content

Usage:  python3 scripts/check-registry-entry.py <registry.json> <plugin-id>
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import urllib.error
import urllib.request
import zipfile

UA = {"User-Agent": "cpa-plugin-registry-check"}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.+-]*$")
GITHUB_PREFIX = "https://github.com/"


def get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def redirect_target(url: str, timeout: int = 30) -> str:
    """Follow a redirect chain without downloading the body.

    GitHub's /releases/latest and /releases/latest/download/<asset> paths do not
    consume the anonymous API rate limit, so they still work when
    api.github.com returns 403.
    """
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl()


def resolve_latest_without_api(owner: str, repo: str) -> str:
    """Return the latest release version, resolved from the HTML redirect."""
    final = redirect_target(f"https://github.com/{owner}/{repo}/releases/latest")
    match = re.search(r"/releases/tag/([^/?#]+)$", final)
    if not match:
        raise AssertionError(f"could not resolve latest tag from redirect: {final}")
    return normalize_version(match.group(1))


def normalize_version(v: str) -> str:
    v = v.strip()
    return v[1:] if len(v) > 1 and v[0] in "vV" else v


def valid_version(v: str) -> bool:
    return bool(v) and not v.startswith("v") and bool(VERSION_RE.match(v))


def repo_parts(repo: str) -> tuple[str, str]:
    repo = repo.strip()
    if not repo.startswith(GITHUB_PREFIX):
        raise AssertionError(f"repository must start with {GITHUB_PREFIX}: {repo!r}")
    rest = repo[len(GITHUB_PREFIX):]
    if rest.count("/") != 1 or rest.endswith("/"):
        raise AssertionError(f"repository must be https://github.com/{{owner}}/{{repo}}: {repo!r}")
    owner, name = rest.split("/")
    return owner, name


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    registry_path, plugin_id = sys.argv[1], sys.argv[2]

    with open(registry_path, encoding="utf-8") as fh:
        registry = json.load(fh)

    # 1. ValidateRegistry
    assert registry.get("schema_version") == 1, f"schema_version must be 1, got {registry.get('schema_version')}"
    ids = [p.get("id", "").strip() for p in registry["plugins"]]
    assert len(ids) == len(set(ids)), "duplicate plugin ids"
    entry = next((p for p in registry["plugins"] if p.get("id") == plugin_id), None)
    assert entry is not None, f"{plugin_id} not found in registry"
    for field in ("id", "name", "description", "author", "repository"):
        assert str(entry.get(field, "")).strip(), f"missing required field {field}"
    assert ID_RE.match(entry["id"]), f"invalid plugin id {entry['id']!r}"
    if entry.get("version"):
        assert valid_version(entry["version"]), f"invalid version {entry['version']!r}"
    owner, repo = repo_parts(entry["repository"])
    print(f"[1/6] registry entry valid: {entry['id']} ({owner}/{repo})")

    # 2. latest release resolves
    goos, goarch = "linux", "amd64"
    api_error = None
    try:
        release = json.loads(get(f"https://api.github.com/repos/{owner}/{repo}/releases/latest"))
        version = normalize_version(release["tag_name"])
        assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
        source = "api.github.com"
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise AssertionError(
                "no published latest release (HTTP 404); publish one before submitting"
            ) from exc
        api_error = exc
        # Rate limited: fall back to the redirect paths, which do not count
        # against the anonymous API quota.
        version = resolve_latest_without_api(owner, repo)
        base = f"https://github.com/{owner}/{repo}/releases/latest/download"
        assets = {n: f"{base}/{n}" for n in ("checksums.txt",)}
        source = "releases/latest redirect (API rate limited)"
    assert valid_version(version), f"invalid release tag {version!r} (need v<dotted numeric>)"
    print(f"[2/6] latest release: version={version} (via {source})")

    # 3. asset names match what the installer computes
    archive_name = f"{entry['id']}_{version}_{goos}_{goarch}.zip"
    if api_error is not None:
        assets[archive_name] = (
            f"https://github.com/{owner}/{repo}/releases/latest/download/{archive_name}"
        )
    assert archive_name in assets, (
        f"release asset {archive_name} not found; has {sorted(assets)}"
    )
    assert "checksums.txt" in assets, "release asset checksums.txt not found"
    print(f"[3/6] assets present: {archive_name}, checksums.txt")

    # 4. checksum verification
    try:
        archive = get(assets[archive_name])
    except urllib.error.HTTPError as exc:
        raise AssertionError(
            f"release asset {archive_name} not downloadable (HTTP {exc.code})"
        ) from exc
    sums = get(assets["checksums.txt"]).decode("utf-8", "replace")
    expected = None
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == archive_name:
            expected = parts[0].lower()
    assert expected is not None, f"{archive_name} missing from checksums.txt"
    actual = hashlib.sha256(archive).hexdigest()
    assert actual == expected, f"sha256 mismatch: file={actual} checksums.txt={expected}"
    print(f"[4/6] sha256 verified: {actual[:16]}… ({len(archive)} bytes)")

    # 5. zip layout: single library at root, correctly named, really a shared lib
    zf = zipfile.ZipFile(io.BytesIO(archive))
    libs = [i for i in zf.infolist() if not i.is_dir() and i.filename.endswith((".so", ".dylib", ".dll"))]
    target = f"{entry['id']}.so"
    versioned = f"{entry['id']}-v{version}.so"
    assert len(libs) == 1, f"zip must hold exactly one dynamic library, found {[i.filename for i in libs]}"
    name = libs[0].filename
    assert "/" not in name, f"dynamic library must be at zip root, got {name!r}"
    assert name in (target, versioned), f"library filename must be {target} or {versioned}, got {name!r}"
    head = zf.read(name)[:20]
    assert head[:4] == b"\x7fELF", "library is not an ELF binary"
    machine = {0x3E: "x86-64", 0xB7: "aarch64"}.get(int.from_bytes(head[18:20], "little"), "?")
    assert machine == "x86-64", f"library arch is {machine}, expected x86-64 for {goos}/{goarch}"
    print(f"[5/6] zip layout ok: {name} ({libs[0].file_size} bytes, ELF64 {machine})")

    # 6. logo asset, if declared
    logo = entry.get("logo")
    if logo:
        data = get(logo)
        assert data, "logo URL returned empty body"
        is_svg = data.lstrip().startswith(b"<svg") or b"<svg" in data[:400]
        is_png = data[:8] == b"\x89PNG\r\n\x1a\n"
        assert is_svg or is_png, f"logo is neither SVG nor PNG ({data[:16]!r})"
        print(f"[6/6] logo ok: {'SVG' if is_svg else 'PNG'} ({len(data)} bytes)")
    else:
        print("[6/6] logo: not declared (optional)")

    print(f"\nOK — {entry['id']} v{version} is installable via the plugin store.")
    print(f"     registry version field: {entry.get('version', '-')} (informational only)")


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except AssertionError as err:
        print(f"FAIL: {err}", file=sys.stderr)
        sys.exit(1)
