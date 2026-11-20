"""Stopped status uses requested mode; synthetic memory fixtures only."""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import network_service
from app.services.secrets_service import MemorySecretStore


PROCESS = {'pid': 100, 'created': 123, 'image': 'synthetic.exe'}


@pytest.mark.parametrize('state,operating,beta,alive,mode,root_name,authentication', [
    ({'status': 'STOPPED'}, True, False, False, 'operating', 'ROOT', 'GOOGLE_ONLY'),
    ({'status': 'STOPPED'}, False, True, False, 'beta-test', 'BETA_ROOT', 'BASIC_AND_GOOGLE'),
    ({'status': 'STOPPED'}, False, False, False, 'isolated', 'DEV_ROOT', 'BASIC_AND_GOOGLE'),
    ({'mode': 'operating'}, False, True, False, 'operating', 'ROOT', 'GOOGLE_ONLY'),
    ({'status': 'STOPPED', 'mode': 'isolated'}, True, False, False, 'isolated', 'DEV_ROOT', 'BASIC_AND_GOOGLE'),
    ({'status': 'STOPPED', 'mode': 'beta-test'}, True, False, False, 'beta-test', 'BETA_ROOT', 'BASIC_AND_GOOGLE'),
    ({'server': PROCESS}, True, False, True, 'isolated', 'DEV_ROOT', 'BASIC_AND_GOOGLE'),
    ({'status': 'STOPPED', 'server': PROCESS}, True, False, True, 'isolated', 'DEV_ROOT', 'BASIC_AND_GOOGLE'),
    ({}, True, False, False, 'isolated', 'DEV_ROOT', 'BASIC_AND_GOOGLE'),
], ids=[
    'stopped-operating', 'stopped-beta', 'stopped-isolated',
    'explicit-operating-preserved', 'explicit-isolated-preserved',
    'explicit-beta-preserved', 'running-missing-mode-no-cli-inference',
    'stale-stopped-owned-process-not-reclassified', 'empty-state-no-cli-inference',
])
def test_status_mode_contract_without_operating_access(monkeypatch, tmp_path,
        state, operating, beta, alive, mode, root_name, authentication):
    original_state = copy.deepcopy(state)
    for name in ('ROOT', 'BETA_ROOT', 'DEV_ROOT'):
        monkeypatch.setattr(network_service, name, tmp_path / name)
    monkeypatch.setattr(network_service, 'OPERATING', operating)
    monkeypatch.setattr(network_service, 'BETA_TEST', beta)
    monkeypatch.setattr(network_service, 'approved_store', lambda: MemorySecretStore())
    monkeypatch.setattr(network_service, 'read_state', lambda: state)
    monkeypatch.setattr(network_service, 'owned', lambda record: bool(record and alive))
    fetches = []
    def fetch(url, store, **kwargs):
        fetches.append((url, kwargs))
        return SimpleNamespace(status_code=200)
    monkeypatch.setattr(network_service, 'fetch', fetch)
    def forbidden(*args, **kwargs):
        pytest.fail('Status must not write state or start/stop real processes')
    for name in ('save_state', 'start', 'stop', 'prepare', 'process_record'):
        monkeypatch.setattr(network_service, name, forbidden)

    result = network_service.status()

    assert result['mode'] == mode
    assert result['dataRoot'] == str(tmp_path / root_name)
    assert result['entryAuthentication'] == authentication
    assert result['serverPid'] == (100 if alive else None)
    assert result['tunnelPid'] is None
    assert result['ngrokRegistered'] is False
    assert result['privateAccessRegistered'] is False
    assert state == original_state
    if alive:
        assert result['localHealth'] == 200
        assert fetches == [(network_service.UPSTREAM, {'local': True})]
    else:
        assert 'localHealth' not in result and 'externalHealth' not in result
        assert fetches == []
