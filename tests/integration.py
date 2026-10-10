#!/usr/bin/env python3
"""Isolated CLIProxyAPI /v1/models integration; never uses production config."""
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

if not __debug__:
    raise SystemExit("This test requires Python assertions; run without -O/-OO or PYTHONOPTIMIZE.")

root = pathlib.Path(sys.argv[1]).resolve()
image = sys.argv[2]
import uuid
name = 'models-context-integration-' + uuid.uuid4().hex[:12]
config = root / 'integration-config.yaml'
config.write_text('''host: "0.0.0.0"
port: 8317
auth-dir: /tmp/test-auth
api-keys:
  - integration-test-only
plugins:
  enabled: true
  dir: /test/plugins
  configs:
    models-context:
      enabled: true
      priority: 1
      context_lengths:
        example-model: 32768
openai-compatibility:
  - name: example-provider
    base-url: https://example.invalid/v1
    api-key-entries:
      - api-key: not-a-...-key
    models:
      - name: example-model
        alias: example-model
''')
plugins = root / 'integration-plugins'
plugins.mkdir(exist_ok=True)
artifacts = list((root / 'dist').glob('*.so'))
assert len(artifacts) == 1, artifacts
(plugins / 'models-context.so').write_bytes(artifacts[0].read_bytes())
created = False
try:
    subprocess.run(['docker', 'create', '--name', name, '--pull=never', '--memory=256m', '--cpus=0.25', '-p', '127.0.0.1::8317', '-v', str(config)+':/test/config.yaml:ro', '-v', str(plugins)+':/test/plugins:ro', image, './CLIProxyAPI', '-config', '/test/config.yaml', '-local-model'], check=True)
    created = True
    subprocess.run(['docker', 'start', name], check=True)
    spec = json.loads(subprocess.check_output(['docker','inspect',name]))[0]
    port = spec['NetworkSettings']['Ports']['8317/tcp'][0]['HostPort']
    url = 'http://127.0.0.1:'+port+'/v1/models'
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer integration-test-only'})
    deadline = time.monotonic()+40
    last = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                result = json.load(response)
            break
        except Exception as exc:
            last = exc
            time.sleep(0.5)
    else:
        raise RuntimeError('Integration server did not become ready: '+str(last))
    entries = [m for m in result['data'] if m['id']=='example-model']
    assert len(entries)==1, result
    assert entries[0]['context_length']==32768, result
    print('INTEGRATION_RESULT', json.dumps(result, sort_keys=True))
    print('PASS: isolated CLIProxyAPI /v1/models advertises configured context_length')
finally:
    if created:
        try:
            subprocess.run(['docker','logs',name], check=False)
        finally:
            subprocess.run(['docker','rm','-f',name],check=True)
