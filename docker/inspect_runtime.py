"""Record real Docker resources and assert all four core services are running."""
from __future__ import annotations

from typing import Any

import argparse
import json
from pathlib import Path
import subprocess

from src.common.artifacts import write_json
from docker.http import request


def json_command(*args: str) -> Any:
    return json.loads(subprocess.check_output(list(args), text=True, timeout=30))


def capture(project: str) -> dict:
    ids = subprocess.check_output(['docker', 'ps', '-a', '-q', '--filter',
        f'label=com.docker.compose.project={project}', '--filter',
        'label=com.docker.compose.oneoff=False'], text=True, timeout=30).split()
    template = ('{"id":{{json .Id}},"image":{{json .Image}},'
        '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
        '"state":{{json .State}},"memory_limit_bytes":{{json .HostConfig.Memory}},'
        '"nano_cpus":{{json .HostConfig.NanoCpus}},"ports":{{json .NetworkSettings.Ports}}}')
    services = {}
    for identifier in ids:
        row = json_command('docker', 'inspect', '--format', template, identifier)
        services[row['service']] = row
    info = json_command('docker', 'info', '--format',
        '{"server_version":{{json .ServerVersion}},"architecture":{{json .Architecture}},'
        '"cpus":{{json .NCPU}},"memory_bytes":{{json .MemTotal}}}')
    errors = []
    for name in ('redis', 'api-server', 'dashboard', 'simulator'):
        row = services.get(name)
        if row is None or not row['state']['Running'] or row['state'].get('OOMKilled'):
            errors.append(f'{name} is not running')
        elif name != 'simulator' and row['state'].get('Health', {}).get('Status') != 'healthy':
            errors.append(f'{name} is not healthy')
    api = services.get('api-server')
    ready = {}
    cgroup = {}
    if api is not None and api['state']['Running']:
        script = ('import json; from pathlib import Path; '
            'print(json.dumps({n:Path("/sys/fs/cgroup",n).read_text().strip() '
            'for n in ("memory.max","memory.peak","memory.swap.current","cpu.max","cpu.stat") '
            'if Path("/sys/fs/cgroup",n).is_file()}))')
        cgroup = json_command('docker', 'exec', api['id'], 'python', '-c', script)
        bindings = api['ports'].get('8000/tcp') or []
        if bindings:
            try:
                ready = request(f"http://127.0.0.1:{bindings[0]['HostPort']}/ready", timeout=5)
                if ready.get('status') != 'ready':
                    errors.append('both API models must be ready')
            except (OSError, ValueError) as error:
                errors.append(f'API readiness failed: {error}')
        else:
            errors.append('API host port missing')
    return dict(status='FAIL' if errors else 'PASS', project=project, engine=info,
                services=services, api_cgroup=cgroup, ready=ready, errors=errors,
                scope='actual four-service state and allocation; quality/latency measured separately')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = capture(args.project)
    write_json(args.output, report)
    print(f"Docker runtime {report['status']}: {args.output}; errors={report['errors']}")
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
