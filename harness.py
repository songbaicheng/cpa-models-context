#!/usr/bin/env python3
"""Offline harness for the models-context CPA plugin.

Loads the built .so with ctypes, performs the same handshake the CPA host does
(cliproxy_plugin_init -> cliproxy_plugin_call with JSON envelopes) and checks
the interception logic. Nothing here touches the running CPA instance.
"""
import base64
import ctypes
import json
import argparse
import sys
from pathlib import Path

if not __debug__:
    raise SystemExit("This test requires Python assertions; run without -O/-OO or PYTHONOPTIMIZE.")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("library", type=Path, help="Path to the built Linux shared library")
args = parser.parse_args()
SO = str(args.library.resolve())


class Buf(ctypes.Structure):
    _fields_ = [("ptr", ctypes.c_void_p), ("len", ctypes.c_size_t)]


HostCallT = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.POINTER(Buf),
)
HostFreeT = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_size_t)


class HostAPI(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("host_ctx", ctypes.c_void_p),
        ("call", HostCallT),
        ("free_buffer", HostFreeT),
    ]


PluginCallT = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_char_p,
    ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.POINTER(Buf),
)
PluginFreeT = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_size_t)
PluginShutdownT = ctypes.CFUNCTYPE(None)


class PluginAPI(ctypes.Structure):
    _fields_ = [
        ("abi_version", ctypes.c_uint32),
        ("call", PluginCallT),
        ("free_buffer", PluginFreeT),
        ("shutdown", PluginShutdownT),
    ]


def host_call(ctx, method, req, reqlen, resp):
    # This plugin never calls back into the host; returning non-zero marks it.
    return 1


lib = ctypes.CDLL(SO)
lib.cliproxy_plugin_init.argtypes = [ctypes.POINTER(HostAPI), ctypes.POINTER(PluginAPI)]
lib.cliproxy_plugin_init.restype = ctypes.c_int
host = HostAPI(1, None, HostCallT(host_call), HostFreeT(lambda p, n: None))
plugin = PluginAPI()
assert lib.cliproxy_plugin_init(None, ctypes.byref(plugin)) != 0
assert lib.cliproxy_plugin_init(ctypes.byref(host), None) != 0
host.abi_version = 2
assert lib.cliproxy_plugin_init(ctypes.byref(host), ctypes.byref(plugin)) != 0
host.abi_version = 1
assert lib.cliproxy_plugin_init(ctypes.byref(host), ctypes.byref(plugin)) == 0
assert plugin.abi_version == 1 and plugin.call and plugin.free_buffer and plugin.shutdown


def call(method, payload=b"", request_length=None):
    buf = (ctypes.c_uint8 * len(payload)).from_buffer_copy(payload) if payload else None
    resp = Buf()
    rc = plugin.call(method.encode() if method else None, buf,
                     len(payload) if request_length is None else request_length,
                     ctypes.byref(resp))
    try:
        data = ctypes.string_at(resp.ptr, resp.len) if resp.ptr else b""
        return rc, json.loads(data)
    finally:
        if resp.ptr:
            plugin.free_buffer(resp.ptr, resp.len)


def configure(text, key="config_yaml"):
    rc, env = call("plugin.reconfigure", json.dumps({
        key: base64.b64encode(text.encode()).decode(), "schema_version": 1,
    }).encode())
    assert rc == 0 and env["ok"]
    return env["result"]


def intercept(body, **extra):
    raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    req = {"Body": base64.b64encode(raw).decode(), "StatusCode": 200, **extra}
    rc, env = call("response.intercept_after", json.dumps(req).encode())
    assert rc == 0 and env["ok"]
    result = env["result"].get("Body")
    return json.loads(base64.b64decode(result)) if result else None


cfg = (Path(__file__).parent / "testdata" / "config.yaml").read_text()
rc, env = call("plugin.register", json.dumps({
    "config_yaml": base64.b64encode(cfg.encode()).decode(), "schema_version": 1,
}).encode())
assert rc == 0 and env["ok"]
meta = env["result"]["metadata"]
for field in ("Name", "Version", "Author", "GitHubRepository"):
    assert str(meta.get(field) or "").strip()
assert meta["Version"] == "1.1.1"
assert env["result"]["capabilities"] == {"response_interceptor": True}
assert env["result"]["context_lengths_loaded"] == 2
models = json.loads((Path(__file__).parent / "testdata" / "models.json").read_text())
result = intercept(models)
assert result["cursor"] == models["cursor"]
assert result["data"][0]["context_length"] == 32768
assert result["data"][1]["context_length"] == 123
assert "context_length" not in result["data"][2]
assert result["data"][0]["large_integer"] == 9007199254740993
for extra in ({"Model": "example-small"}, {"RequestedModel": "example-small"},
              {"Stream": True}, {"StatusCode": 500}):
    assert intercept(models, **extra) is None
for body in ("not json", "null", {"object": "list", "data": []},
             {"object": "list", "data": [{"id": "example-small", "object": "file"}]},
             {"object": "list", "data": [{"id": "example-small"}]},
             {"object": "other", "data": [{"id": "example-small", "object": "model"}]}):
    assert intercept(body) is None
for raw in (b"{", b"{}", b'{"config_yaml":123}'):
    configure(cfg)
    assert call("plugin.reconfigure", raw)[1]["result"]["context_lengths_loaded"] == 0
    assert intercept(models) is None
configure("context_lengths: '{\"example-small\":8192}'\n", "ConfigYAML")
assert intercept(models)["data"][0]["context_length"] == 8192
configure("probe: true\n" + cfg)
assert intercept({"choices": [{"message": {"content": "private fixture"}}]},
                 Model="example-small") is None
for method in ("response.intercept_before", "plugin.quiesce"):
    assert call(method)[1] == {"ok": True, "result": {}}
assert call("unknown.method")[1]["ok"] is False
assert call(None)[0] != 0
assert call("plugin.register", request_length=1)[0] != 0
assert call("plugin.register", request_length=2147483648)[0] != 0
assert plugin.call(b"plugin.quiesce", None, 0, None) != 0
plugin.free_buffer(None, 0)
plugin.shutdown()
print("C ABI smoke checks passed (offline; not host integration)")
