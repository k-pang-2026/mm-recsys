#!/usr/bin/env python3
"""호스트의 demo 명령을 현재 Compose 배포의 API·실험·CT 실행기에 연결합니다."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.common.console import configure_utf8

COMMANDS = ('search', 'recommend', 'session', 'ab', 'ct', 'examples', 'evaluate', 'verify-peer-review')


def install() -> None:
    if os.name != 'posix':
        raise ValueError('이 등록 방식은 Linux/WSL/macOS용입니다. Windows에서는 python scripts/demo_host.py <명령>을 사용하세요.')
    target, source = Path.home() / '.local/bin/demo', Path(__file__).resolve()
    if target.is_symlink() and target.resolve() == source:
        print(f'demo 등록 확인: {target}')
        return
    if target.exists() or target.is_symlink():
        raise FileExistsError(f'기존 명령을 덮어쓰지 않습니다: {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source)
    print(f'demo 등록 완료: {target}')
    if str(target.parent) not in os.get_exec_path():
        print('현재 셸에서 export PATH="$HOME/.local/bin:$PATH"를 한 번 실행하세요.')


def find_api(project: str | None) -> dict:
    command = ['docker', 'ps', '-q', '--filter', 'label=com.docker.compose.service=api-server',
               '--filter', 'label=com.docker.compose.oneoff=False', '--filter',
               f'label=com.docker.compose.project.working_dir={ROOT}']
    if project:
        command += ['--filter', f'label=com.docker.compose.project={project}']
    ids = subprocess.check_output(command, text=True).split()
    if not ids:
        raise ValueError('실행 중인 API가 없습니다. 저장소에서 docker compose up --build를 먼저 실행하세요.')
    if len(ids) != 1:
        raise ValueError('같은 저장소의 API가 여러 개 실행 중입니다. demo --project <이름> <명령>으로 선택하세요.')
    return json.loads(subprocess.check_output(['docker', 'inspect', ids[0]], text=True))[0]


def command_for(container: dict, command: str, arguments: list[str]) -> tuple[list[str], dict[str, str]]:
    labels = container['Config']['Labels']
    compose = ['docker', 'compose', '-p', labels['com.docker.compose.project']]
    for name in labels['com.docker.compose.project.config_files'].split(','):
        if not Path(name).is_file():
            raise ValueError(f'배포에 사용한 Compose 파일이 없습니다: {name}')
        compose += ['-f', name]
    deployed = dict(item.split('=', 1) for item in container['Config']['Env'] if '=' in item)
    env = dict(os.environ)
    for name in ('SCALE', 'RUNTIME_RESULTS_DIR', 'SERVING_THREADS', 'SERVING_PARALLEL_HYBRID',
                 'SERVING_OPTIMIZE_VISION', 'SERVING_GC_FREEZE'):
        if name in deployed:
            env[name] = deployed[name]
    # Reuse the exact deployment files/project; never guess a different running stack.
    arguments = list(arguments)
    for i, argument in enumerate(arguments):
        if argument in ('--output', '--output-dir') and i + 1 < len(arguments):
            position, prefix, value = i + 1, '', arguments[i + 1]
        elif argument.startswith(('--output=', '--output-dir=')):
            option, value = argument.split('=', 1)
            position, prefix = i, option + '='
        else:
            continue
        destination = (ROOT / value).resolve()
        if not destination.is_relative_to(ROOT / 'docs/results'):
            raise ValueError('결과는 호스트에 보존되는 저장소 docs/results/ 아래 경로를 지정하세요.')
        arguments[position] = prefix + destination.relative_to(ROOT).as_posix()
    volumes = []
    for i, argument in enumerate(arguments):
        if argument == '--query-image' and i + 1 < len(arguments):
            position, prefix, value = i + 1, '', arguments[i + 1]
        elif argument.startswith('--query-image='):
            position, prefix, value = i, '--query-image=', argument.split('=', 1)[1]
        else:
            continue
        if Path(value).is_file():
            source = Path(value).resolve()
            target = '/tmp/demo-query' + source.suffix
            volumes = ['--volume', f'{source}:{target}:ro']
            arguments[position] = prefix + target
    production_ct = command == 'ct' and any(flag in arguments for flag in ('--train', '--rollback'))
    if production_ct:
        compose += ['-f', str(ROOT / 'docker/compose.ct.yml'), '--profile', 'ct']
        if '--reload-url' not in arguments:
            arguments += ['--reload-url', 'http://127.0.0.1:8000']
        invocation = compose + ['run', '--rm', '--no-deps', '--build', 'ct']
    elif volumes or command in ('ab', 'examples', 'evaluate') or command == 'ct' and '--drill' in arguments:
        invocation = compose + ['run', '--rm', '--no-deps', '--pull', 'never', *volumes, 'api-server']
    else:
        invocation = compose + ['exec', '-T', 'api-server']
    return invocation + ['demo', command, *arguments], env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog='예: demo search --query-text "검정 오버핏 후드티" / demo ab / demo ct / demo examples')
    parser.add_argument('--install', action='store_true', help='Linux/WSL/macOS의 ~/.local/bin/demo에 한 번 등록')
    parser.add_argument('--project', help='같은 저장소에 여러 배포가 실행 중일 때 선택')
    parser.add_argument('command', nargs='?', choices=COMMANDS)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.install:
        install()
        return 0
    if args.command is None:
        parser.print_help()
        return 0
    invocation, env = command_for(find_api(args.project), args.command, args.arguments)
    return subprocess.call(invocation, cwd=ROOT, env=env)


if __name__ == '__main__':
    configure_utf8()
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode)
    except (OSError, ValueError) as error:
        print(f'[demo 실패] {error}', file=sys.stderr)
        raise SystemExit(1)
