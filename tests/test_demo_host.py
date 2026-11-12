"""Host demo must keep heavy jobs out of the API and target the selected deployment."""
import json
from pathlib import Path

import pytest

from scripts import demo_host


@pytest.fixture
def container(tmp_path):
    compose = tmp_path / 'compose with spaces.yaml'
    compose.write_text('services: {}')
    return {'Config': {'Labels': {'com.docker.compose.project': 'actual-project',
        'com.docker.compose.project.config_files': str(compose)},
        'Env': ['SCALE=full', 'RUNTIME_RESULTS_DIR=docs/results/actual', 'SERVING_THREADS=2']}}


@pytest.mark.parametrize(('command','arguments','operation','service'), [
    ('search', ['--query-text','검정 오버핏 후드티'], 'exec', 'api-server'),
    ('recommend', ['--user-id','U000001'], 'exec', 'api-server'),
    ('ab', [], 'run', 'api-server'),
    ('examples', [], 'run', 'api-server'),
    ('ct', [], 'exec', 'api-server'),
    ('ct', ['--drill'], 'run', 'api-server'),
    ('ct', ['--train'], 'run', 'ct'),
    ('ct', ['--rollback','v1.0'], 'run', 'ct'),
])
def test_command_placement_and_selected_runtime(container, monkeypatch, command, arguments, operation, service):
    monkeypatch.setenv('SCALE', 'dev')
    args, env = demo_host.command_for(container, command, arguments)
    assert args[:4] == ['docker','compose','-p','actual-project']
    assert operation in args and args[args.index('demo') - 1] == service
    assert env['SCALE'] == 'full' and env['RUNTIME_RESULTS_DIR'] == 'docs/results/actual'
    if service == 'ct':
        assert '--profile' in args and args[-2:] == ['--reload-url','http://127.0.0.1:8000']


@pytest.mark.parametrize('compact', [False, True])
def test_host_image_is_mounted_readonly_without_shell_interpolation(container, tmp_path, compact):
    image = tmp_path / 'image with spaces.png'
    image.write_bytes(b'image')
    query = 'literal $(must-not-execute)'
    image_args = ['--query-image='+str(image)] if compact else ['--query-image',str(image)]
    args, _ = demo_host.command_for(container, 'search', ['--query-text', query, *image_args])
    assert 'run' in args and query in args
    assert args[args.index('--volume') + 1] == f'{image}:/tmp/demo-query.png:ro'
    assert args[-1] == ('--query-image=' if compact else '') + '/tmp/demo-query.png'


@pytest.mark.parametrize('ids', ['', 'one\ntwo\n'])
def test_ambiguous_or_absent_deployment_is_never_guessed(monkeypatch, ids):
    monkeypatch.setattr(demo_host.subprocess, 'check_output', lambda *a, **kw: ids)
    with pytest.raises(ValueError):
        demo_host.find_api(None)


def test_find_api_excludes_oneoff_jobs_and_other_checkouts(monkeypatch, container):
    calls = []
    def output(args, **kw):
        calls.append(args)
        return 'actual-id\n' if len(calls) == 1 else json.dumps([container])
    monkeypatch.setattr(demo_host.subprocess, 'check_output', output)
    assert demo_host.find_api('actual-project') == container
    assert 'label=com.docker.compose.oneoff=False' in calls[0]
    assert f'label=com.docker.compose.project.working_dir={demo_host.ROOT}' in calls[0]
    assert calls[1] == ['docker','inspect','actual-id']


@pytest.mark.parametrize('option', ['--output', '--output-dir'])
def test_results_cannot_disappear_with_temporary_container(container, tmp_path, option):
    with pytest.raises(ValueError, match='docs/results'):
        demo_host.command_for(container, 'examples', [option, str(tmp_path / 'lost')])
    with pytest.raises(ValueError, match='docs/results'):
        demo_host.command_for(container, 'examples', [option + '=docs/results/../../../lost'])
    output = demo_host.ROOT / 'docs/results/demo/result.json'
    args, _ = demo_host.command_for(container, 'examples', [option + '=' + str(output)])
    assert args[-1] == option + '=docs/results/demo/result.json'


@pytest.mark.skipif(demo_host.os.name != 'posix', reason='POSIX user command registration')
def test_install_preserves_existing_user_command(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    demo_host.install()
    target = tmp_path / '.local/bin/demo'
    assert target.resolve() == Path(demo_host.__file__).resolve()
    demo_host.install()
    target.unlink()
    target.write_text('existing user command')
    with pytest.raises(FileExistsError):
        demo_host.install()
    assert target.read_text() == 'existing user command'
