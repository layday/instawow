import json
from pathlib import Path
import sys

import pytest

from instawow.config import Config


def test_env_vars_have_prio(full_config, monkeypatch):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', '/foo')
    monkeypatch.setenv('INSTAWOW_GAME_FLAVOUR', 'classic')
    config = Config(**full_config)
    assert config.config_dir == Path('/foo')
    assert config.game_flavour == 'classic'


def test_config_dir_is_populated(full_config):
    config = Config(**full_config).write()
    assert {i.name for i in config.config_dir.iterdir()} == {'config.json', 'logs', 'plugins'}


def test_reading_missing_config_from_env_raises(full_config, monkeypatch):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(full_config['config_dir']))
    with pytest.raises(FileNotFoundError):
        Config.read()


def test_invalid_any_dir_raises(full_config):
    with pytest.raises(ValueError):
        Config(**{**full_config, 'addon_dir': '~foo'})


def test_invalid_addon_dir_raises(full_config):
    with pytest.raises(ValueError, match='must be a writable directory'):
        Config(**{**full_config, 'addon_dir': 'foo'})


def test_reading_existing_config_values(full_config):
    config = Config(**full_config).write()
    config_json = {'addon_dir': str(full_config['addon_dir']),
                   'temp_dir': str(full_config['temp_dir']),
                   'game_flavour': config.game_flavour}
    assert config_json == json.loads((full_config['config_dir'] / 'config.json').read_text())


def test_default_config_dir_is_platform_xdg_compliant(partial_config, monkeypatch):
    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'linux')
        config_dir = Config(**partial_config).config_dir
        assert config_dir == Path.home() / '.config/instawow'

        patcher.setenv('XDG_CONFIG_HOME', '/foo')
        config_dir = Config(**partial_config).config_dir
        assert config_dir == Path('/foo/instawow')

    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'darwin')
        config_dir = Config(**partial_config).config_dir
        assert config_dir == Path.home() / 'Library/Application Support/instawow'
