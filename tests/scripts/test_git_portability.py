"""Git tooling must select project metadata independently of the caller's cwd."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('portable_env_capture', ROOT / 'scripts/env_capture.py')
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)
PILOT_SPEC = importlib.util.spec_from_file_location('portable_pilot', ROOT / 'scripts/run_p5_pilot.py')
pilot = importlib.util.module_from_spec(PILOT_SPEC)
PILOT_SPEC.loader.exec_module(pilot)


@pytest.fixture(autouse=True)
def isolated_git_environment(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith('GIT_'):
            monkeypatch.delenv(name)
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)


def git(*args, cwd):
    return subprocess.run(['git', *map(str, args)], cwd=cwd, check=True,
                          capture_output=True, text=True, timeout=15)


def copy_wrapper(root):
    scripts = root / 'scripts'
    scripts.mkdir(parents=True, exist_ok=True)
    wrapper = scripts / 'git.sh'
    shutil.copy2(ROOT / 'scripts/git.sh', wrapper)
    return wrapper


def repository(tmp_path, kind):
    root = tmp_path / 'project with spaces'
    root.mkdir()
    wrapper = copy_wrapper(root)
    if kind == 'managed':
        # The empty host-owned directory is not a usable fallback repository.
        (root / '.git').mkdir()
        git('init', '--quiet', '--bare', root / '.tiplog-git', cwd=tmp_path)
        base = [f'--git-dir={root / ".tiplog-git"}', f'--work-tree={root}']
    elif kind == 'worktree':
        original = tmp_path / 'original'
        original.mkdir()
        git('init', '--quiet', cwd=original)
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
            'commit', '--quiet', '--allow-empty', '-m', 'fixture', cwd=original)
        # Git permits an existing worktree destination only when it is empty.
        wrapper.unlink()
        wrapper.parent.rmdir()
        git('worktree', 'add', '--quiet', '--detach', root, 'HEAD', cwd=original)
        copy_wrapper(root)
        return root, wrapper
    else:
        git('init', '--quiet', cwd=root)
        base = []
    git(*base, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
        'commit', '--quiet', '--allow-empty', '-m', 'fixture', cwd=root)
    return root, wrapper


@pytest.mark.parametrize('kind', ['managed', 'normal', 'worktree'])
def test_wrapper_reads_project_from_unrelated_cwd(tmp_path, kind):
    root, wrapper = repository(tmp_path, kind)
    elsewhere = tmp_path / 'unrelated'
    elsewhere.mkdir()
    before = sorted((root / '.git').iterdir()) if kind == 'managed' else None
    result = subprocess.run([str(wrapper), 'rev-parse', '--show-toplevel'], cwd=elsewhere,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()) == root
    failure = subprocess.run([str(wrapper), 'rev-parse', '--verify', 'missing-ref'], cwd=elsewhere,
                             capture_output=True, text=True, timeout=15)
    assert failure.returncode != 0 and failure.stderr
    if kind == 'managed':
        assert sorted((root / '.git').iterdir()) == before == []


@pytest.mark.parametrize('kind', ['managed', 'normal', 'worktree'])
def test_environment_capture_records_selected_git_metadata(tmp_path, monkeypatch, kind):
    root, _ = repository(tmp_path, kind)
    monkeypatch.setattr(capture, 'ROOT', root)
    monkeypatch.chdir(tmp_path)
    result = capture.git_info()
    assert result['metadata'] == str(root / ('.tiplog-git' if kind == 'managed' else '.git'))
    assert result['managed_metadata_preserved'] == (str(root / '.git') if kind == 'managed' else None)
    assert result['sha'] and len(result['sha']) == 40
    assert result['head']['returncode'] == result['status']['returncode'] == 0
    assert result['dirty'] is True  # The copied wrapper is intentionally untracked.
    assert result['unborn_head_allowed_at_bootstrap'] is False


@pytest.mark.parametrize('kind', ['managed', 'normal', 'worktree'])
def test_pilot_provenance_labels_actual_metadata_without_running_measurements(tmp_path, monkeypatch, kind):
    root, _ = repository(tmp_path, kind)
    monkeypatch.setattr(pilot, 'ROOT', root)
    monkeypatch.chdir(tmp_path)
    result = pilot.git_info()
    assert result['metadata'] == ('.tiplog-git' if kind == 'managed' else '.git')
    assert result['managed_git_preserved'] is (kind == 'managed')
    assert len(result['sha']) == 40
    assert result['dirty'] is True and 'scripts/' in result['status_porcelain']


def test_missing_metadata_never_uses_enclosing_repository(tmp_path, monkeypatch):
    git('init', '--quiet', cwd=tmp_path)
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
        'commit', '--quiet', '--allow-empty', '-m', 'unrelated parent', cwd=tmp_path)
    root = tmp_path / 'exported project'
    wrapper = copy_wrapper(root)
    result = subprocess.run([str(wrapper), 'rev-parse', '--verify', 'HEAD'], cwd=tmp_path,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 128
    assert 'No Git metadata found' in result.stderr
    assert result.stdout == ''
    monkeypatch.setattr(capture, 'ROOT', root)
    evidence = capture.git_info()
    assert evidence['sha'] is evidence['dirty'] is None
    assert evidence['head']['returncode'] != 0 and evidence['status']['returncode'] != 0
    assert evidence['unborn_head_allowed_at_bootstrap'] is False


@pytest.mark.parametrize('kind', ['empty_directory', 'invalid_file', 'broken_pointer'])
def test_invalid_normal_metadata_never_uses_enclosing_repository(tmp_path, monkeypatch, kind):
    git('init', '--quiet', cwd=tmp_path)
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
        'commit', '--quiet', '--allow-empty', '-m', 'unrelated parent', cwd=tmp_path)
    root = tmp_path / 'exported project'
    wrapper = copy_wrapper(root)
    if kind == 'empty_directory':
        (root / '.git').mkdir()
    else:
        (root / '.git').write_text('gitdir: missing\n' if kind == 'broken_pointer' else 'invalid\n')
    result = subprocess.run([str(wrapper), 'rev-parse', '--verify', 'HEAD'], cwd=tmp_path,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode != 0 and result.stderr
    assert result.stdout == ''
    monkeypatch.setattr(capture, 'ROOT', root)
    evidence = capture.git_info()
    assert evidence['sha'] is evidence['dirty'] is None
    assert evidence['head']['returncode'] != 0 and evidence['status']['returncode'] != 0
    monkeypatch.setattr(pilot, 'ROOT', root)
    with pytest.raises(subprocess.CalledProcessError):
        pilot.git_info()


def test_invalid_managed_metadata_does_not_fall_back_to_normal_git(tmp_path, monkeypatch):
    root, wrapper = repository(tmp_path, 'normal')
    (root / '.tiplog-git').mkdir()
    result = subprocess.run([str(wrapper), 'rev-parse', '--verify', 'HEAD'], cwd=tmp_path,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode != 0 and result.stderr
    monkeypatch.setattr(capture, 'ROOT', root)
    evidence = capture.git_info()
    assert evidence['metadata'] == str(root / '.tiplog-git')
    assert evidence['sha'] is evidence['dirty'] is None


@pytest.mark.parametrize('kind', ['managed', 'normal'])
def test_environment_capture_distinguishes_unborn_head_from_missing_metadata(tmp_path, monkeypatch, kind):
    root = tmp_path / 'new project'
    copy_wrapper(root)
    if kind == 'managed':
        (root / '.git').mkdir()
        git('init', '--quiet', '--bare', root / '.tiplog-git', cwd=tmp_path)
    else:
        git('init', '--quiet', cwd=root)
    monkeypatch.setattr(capture, 'ROOT', root)
    evidence = capture.git_info()
    assert evidence['sha'] is None
    assert evidence['head']['returncode'] != 0
    assert evidence['status']['returncode'] == 0
    assert evidence['unborn_head_allowed_at_bootstrap'] is True
