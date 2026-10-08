"""Bootstrap regressions run in temporary projects without installing ML packages."""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, cwd: Path = ROOT, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)


class SetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix='mm-bootstrap-', dir='/tmp')
        self.base = Path(self.temp.name)
        self.project = self.base / 'project with spaces'

    def tearDown(self) -> None:
        self.temp.cleanup()

    def scaffold(self, *extra: str) -> subprocess.CompletedProcess:
        result = run('bash', str(ROOT / 'setup_env.sh'), str(self.project),
                     '--scaffold-only', '--skip-docker-check', *extra)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_scaffold_files_and_pins(self) -> None:
        result = self.scaffold()
        self.assertIn('미측정', result.stdout)
        self.assertFalse((self.project / '.venv').exists())
        for p in self.project.rglob('*.py'):
            ast.parse(p.read_text(), filename=str(p))
        cfg = yaml.safe_load((self.project / 'config.yaml').read_text())
        self.assertEqual(cfg['scales']['full']['n_products'], 50000)
        self.assertEqual(cfg['search']['faiss']['type'], 'HNSW')
        self.assertEqual(cfg['recommend']['candidate']['negatives_per_positive'], 4)
        self.assertEqual(cfg['recommend']['evaluation']['k'], 300)
        compose = yaml.safe_load((self.project / 'docker-compose.yml').read_text())
        self.assertEqual(set(compose['services']), {'redis', 'api-server', 'dashboard', 'simulator'})
        self.assertEqual(compose['services']['api-server']['mem_limit'], '4g')
        for name in ('requirements.txt', 'requirements-torch.txt', 'requirements-dashboard.txt'):
            lines = (self.project / name).read_text().splitlines()
            self.assertTrue(all('==' in line for line in lines if line and not line.startswith('#')))
        for name in ('api', 'simulator'):
            text = (self.project / f'docker/Dockerfile.{name}').read_text()
            self.assertIn('-r requirements-torch.txt', text)
        for name in ('docs/team_workflow.md', 'docs/contracts.md', 'scripts/step_git.py', 'setup_env.sh', '.github/workflows/ci.yml'):
            self.assertEqual((ROOT / name).read_bytes(), (self.project / name).read_bytes())
        self.assertEqual((ROOT / 'ai_step_prompts_optimized.md').read_bytes(),
                         (self.project / 'docs/ai_step_prompts.md').read_bytes())
        for p in (self.project / 'docs/results/gates').glob('*.json'):
            self.assertEqual(p.read_bytes(), (ROOT / 'docs/results/gates' / p.name).read_bytes())

    def test_rerun_preserves_edits_and_explicitly_refreshes_prompts(self) -> None:
        self.scaffold()
        path = self.project / 'config.yaml'
        modified = path.read_text() + '\n# user change\n'
        path.write_text(modified)
        prompts = self.project / 'docs/ai_step_prompts.md'
        prompts.write_text('old prompts')
        result = self.scaffold()
        self.assertIn('--refresh-prompts', result.stdout)
        self.assertEqual(path.read_text(), modified)
        self.assertEqual(prompts.read_text(), 'old prompts')
        self.scaffold('--refresh-prompts')
        self.assertEqual(path.read_text(), modified)
        self.assertEqual(prompts.read_bytes(), (ROOT / 'ai_step_prompts_optimized.md').read_bytes())

    def test_default_existing_clone_has_no_nested_project(self) -> None:
        self.scaffold()
        result = run('bash', str(ROOT / 'setup_env.sh'), '--scaffold-only',
                     '--skip-docker-check', cwd=self.project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.project / 'mm-recsys').exists())

    def test_nested_repository_is_rejected(self) -> None:
        self.scaffold()
        nested = self.project / 'nested'
        result = run('bash', str(ROOT / 'setup_env.sh'), str(nested), '--scaffold-only', '--skip-docker-check')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('저장소 루트', result.stdout)
        self.assertFalse((nested / '.git').exists())

    def test_conflicting_options_fail_before_writes(self) -> None:
        result = run('bash', str(ROOT / 'setup_env.sh'), str(self.project), '--scaffold-only', '--prefetch-clip')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.project.exists())

    def test_config_overrides_and_no_mutation(self) -> None:
        self.scaffold()
        script = '''
import os
from src.common.config import load_config
os.environ['SCALE'] = 'full'
os.environ['CONFIG_PATH'] = 'config.yaml'
os.environ['REDIS_HOST'] = 'localhost'
os.environ['REDIS_PORT'] = '6380'
cfg = load_config()
assert cfg['simulator']['n_products'] == 50000
assert cfg['redis'] == {'host': 'localhost', 'port': 6380}
cfg['search']['faiss']['M'] = 99
assert load_config()['search']['faiss']['M'] == 32
os.environ['SCALE'] = 'invalid'
try: load_config()
except ValueError: pass
else: raise AssertionError('invalid scale accepted')
os.environ['SCALE'] = 'dev'
os.environ['REDIS_PORT'] = '70000'
try: load_config()
except ValueError: pass
else: raise AssertionError('invalid port accepted')
'''
        result = run(sys.executable, '-c', script, cwd=self.project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_install_failure_is_nonzero_without_success_banner(self) -> None:
        # Simulate a failed installer, never download dependencies in this regression.
        self.scaffold()
        bindir = self.project / '.venv/bin'
        bindir.mkdir(parents=True)
        wrapper = bindir / 'python'
        wrapper.write_text('#!/usr/bin/env bash\nif [ "$1" = "-m" ] && [ "$2" = "pip" ]; then exit 23; fi\nexec ' + sys.executable + ' -S "$@"\n')
        wrapper.chmod(0o755)
        result = run('bash', str(ROOT / 'setup_env.sh'), str(self.project), '--skip-docker-check')
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertNotIn('환경 설치 및 스모크 검증 완료', result.stdout)


class GitHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        spec = importlib.util.spec_from_file_location('step_git', ROOT / 'scripts/step_git.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory(prefix='mm-git-check-', dir='/tmp')
        self.repo = Path(self.temp.name)
        for args in [('init', '-q', '-b', 'main'), ('config', 'user.name', 'Test Fixture'),
                     ('config', 'user.email', 'fixture@example.invalid'),
                     ('remote', 'add', 'origin', 'https://github.com/example/test.git'),
                     ('switch', '-c', 'feat/A/B2a-fixture')]:
            result = run('git', *args, cwd=self.repo)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.gate = {'step': 'B2a', 'owner': 'A', 'status': 'PASS', 'scale': 'dev',
                     'acceptance': 'UNMEASURED', 'data_fingerprint': 'fixture-data',
                     'config_fingerprint': 'fixture-config', 'evaluation_version': 'fixture-v1',
                     'commands': [{'command': 'fixture validation', 'exit_code': 0}]}
        (self.repo / 'docs/results/gates').mkdir(parents=True)
        self.gate_path = self.repo / 'docs/results/gates/B2a.json'
        self.gate_path.write_text(json.dumps(self.gate))
        (self.repo / 'change.py').write_text('x = 1\n')

    def tearDown(self) -> None:
        self.temp.cleanup()

    def helper(self, *extra: str) -> subprocess.CompletedProcess:
        return run(sys.executable, str(ROOT / 'scripts/step_git.py'), '--step', 'B2a',
                   '--role', 'A', '--files', 'change.py', 'docs/results/gates/B2a.json',
                   *extra, cwd=self.repo)

    def test_check_mode_never_commits_or_stages(self) -> None:
        result = self.helper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('CHECK ONLY', result.stdout)
        self.assertEqual(run('git', 'diff', '--cached', '--name-only', cwd=self.repo).stdout, '')
        self.assertNotEqual(run('git', 'rev-parse', '--verify', 'HEAD', cwd=self.repo).returncode, 0)

    def test_invalid_gate_and_fake_dev_acceptance_rejected(self) -> None:
        for key, value in [('status', 'FAIL'), ('acceptance', 'PASS'), ('commands', [])]:
            invalid = {**self.gate, key: value}
            with self.assertRaises(ValueError):
                self.module.check_gate(invalid, 'B2a', 'A')

    def test_main_and_existing_staging_rejected(self) -> None:
        run('git', 'switch', '-c', 'main', cwd=self.repo)
        self.assertNotEqual(self.helper().returncode, 0)
        run('git', 'symbolic-ref', 'HEAD', 'refs/heads/feat/A/B2a-fixture', cwd=self.repo)
        run('git', 'add', 'change.py', cwd=self.repo)
        result = self.helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('staged', result.stderr)

    def test_publish_scopes_commit_and_reports_push_failure(self) -> None:
        # The push is intercepted locally; this test never accesses GitHub.
        shim_dir = self.repo / 'test-bin'
        shim_dir.mkdir()
        shim = shim_dir / 'git'
        real_git = shutil.which('git')
        shim.write_text('#!' + sys.executable + '\nimport os, sys\n'
                        'if sys.argv[1] == "push": sys.exit(41)\n'
                        'os.execv(' + repr(real_git) + ', [' + repr(real_git) + '] + sys.argv[1:])\n')
        shim.chmod(0o755)
        (self.repo / 'unrelated.txt').write_text('preserve me')
        env = {**os.environ, 'PATH': str(shim_dir) + os.pathsep + os.environ['PATH']}
        prepared = self.helper('--mode', 'commit')
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        self.assertIn('AWAITING PUSH APPROVAL', prepared.stdout)
        message = run('git', 'log', '-1', '--format=%B', cwd=self.repo).stdout
        self.assertRegex(message.splitlines()[0], r'^(feat|fix|test|docs|chore)\([a-z]+\): .*[가-힣]')
        self.assertIn('변경 사항:', message)
        self.assertIn('추가: change.py', message)
        self.assertIn('검증 결과:', message)
        self.assertIn('단계: B2a', message)
        result = run(sys.executable, str(ROOT / 'scripts/step_git.py'), '--step', 'B2a',
                     '--role', 'A', '--mode', 'publish', '--approved', '--files', 'change.py',
                     'docs/results/gates/B2a.json', cwd=self.repo, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('BLOCKED', result.stderr)
        self.assertEqual(json.loads((self.repo / '.team/pending_publication.json').read_text())['status'], 'PUSH_APPROVED')
        committed = run('git', 'ls-tree', '-r', '--name-only', 'HEAD', cwd=self.repo).stdout.splitlines()
        self.assertEqual(set(committed), {'change.py', 'docs/results/gates/B2a.json'})
        self.assertTrue((self.repo / 'unrelated.txt').exists())

    def test_publish_without_approval_does_not_stage_commit_or_push(self) -> None:
        result = self.helper('--mode', 'publish')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('explicit user approval', result.stderr)
        self.assertEqual(run('git', 'diff', '--cached', '--name-only', cwd=self.repo).stdout, '')
        self.assertNotEqual(run('git', 'rev-parse', '--verify', 'HEAD', cwd=self.repo).returncode, 0)

    def test_approval_is_bound_to_the_reviewed_commit(self) -> None:
        self.assertEqual(self.helper('--mode', 'commit').returncode, 0)
        run('git', 'commit', '--allow-empty', '-m', 'new unreviewed commit', cwd=self.repo)
        result = self.helper('--mode', 'publish', '--approved')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('changed since review', result.stderr)

    def test_docs_only_commit_uses_common_rule_and_korean_diff_summary(self) -> None:
        (self.repo / 'guide.md').write_text('문서 수정 예제')
        result = self.helper('--mode', 'commit', '--files', 'guide.md', 'docs/results/gates/B2a.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        message = run('git', 'log', '-1', '--format=%B', cwd=self.repo).stdout
        self.assertTrue(message.startswith('docs(search): '))
        self.assertIn('추가: guide.md', message)

    def test_invalid_commit_summary_is_rejected_before_staging(self) -> None:
        self.gate_path.write_text(json.dumps({**self.gate, 'commit_summary_ko': 'English only summary'}))
        result = self.helper('--mode', 'commit')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Korean line', result.stderr)
        self.assertEqual(run('git', 'diff', '--cached', '--name-only', cwd=self.repo).stdout, '')

    def test_deleted_tracked_file_is_committed_and_described_in_korean(self) -> None:
        (self.repo / 'guide.md').write_text('삭제 동작 검사')
        first = self.helper('--mode', 'commit', '--files', 'guide.md', 'docs/results/gates/B2a.json')
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        (self.repo / 'guide.md').unlink()
        result = self.helper('--mode', 'commit', '--files', 'guide.md', 'docs/results/gates/B2a.json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        message = run('git', 'log', '-1', '--format=%B', cwd=self.repo).stdout
        self.assertIn('삭제: guide.md', message)
        self.assertNotIn('guide.md', run('git', 'ls-tree', '-r', '--name-only', 'HEAD', cwd=self.repo).stdout)

    def test_private_paths_and_symlinks_rejected(self) -> None:
        for name in ('.env.local', 'weights.pt', 'secret.pem'):
            (self.repo / name).write_text('fixture')
            with self.assertRaises(ValueError):
                self.module.validate_path(self.repo, name)
        with self.assertRaises(ValueError):
            self.module.validate_path(self.repo, '../outside')
        (self.repo / 'linked.py').symlink_to(self.repo / 'change.py')
        with self.assertRaises(ValueError):
            self.module.validate_path(self.repo, 'linked.py')


if __name__ == '__main__':
    unittest.main()
