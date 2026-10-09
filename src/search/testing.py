"""Test-only plugin: missing-model contracts must not depend on local model caches."""
import pytest


@pytest.fixture(autouse=True)
def isolated_search_artifacts(monkeypatch, tmp_path):
    # The original shared API contract tests explicitly exercise the model-absent state.
    # Tests constructing a real fixture bundle may remove this override explicitly.
    # Real checkpoint evaluation/HTTP benchmarks are separate CLI processes, not pytest.
    monkeypatch.setenv('SEARCH_MODEL_DIR', str(tmp_path/'unprepared-search-models'))
