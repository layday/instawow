import json
from pathlib import Path
import sys

import pytest

from instawow.config import Config


def test_env_vars_have_prio(full_config, monkeypatch):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', '/foo')
    monkeypatch.setenv('INSTAWOW_GAME_FLAVOUR', 'classic')

    config = Config(**full_config)
    assert config.config_dir == Path('/foo').resolve()
    assert config.game_flavour == 'classic'


def test_config_dir_is_populated(full_config):
    config = Config(**full_config).write()
    assert {i.name for i in config.config_dir.iterdir()} == {'config.json', 'logs', 'plugins'}


def test_reading_missing_config_from_env_raises(full_config, monkeypatch):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(full_config['config_dir']))
    with pytest.raises(FileNotFoundError):  # type: ignore
        Config.read()


@pytest.mark.skipif(sys.platform == 'win32', reason='no ~ expansion on Windows')
@pytest.mark.parametrize('dir_', ['config_dir', 'addon_dir', 'temp_dir'])
def test_invalid_any_dir_raises(full_config, dir_):
    with pytest.raises(ValueError):  # type: ignore
        Config(**{**full_config, dir_: '~foo'})


def test_invalid_addon_dir_raises(full_config):
    with pytest.raises(ValueError, match='must be a writable directory'):  # type: ignore
        Config(**{**full_config, 'addon_dir': 'foo'})


def test_reading_config_file(full_config):
    Config(**full_config).write()
    config_json = {
        'addon_dir': str(full_config['addon_dir']),
        'game_flavour': full_config['game_flavour'],
    }
    assert config_json == json.loads((full_config['config_dir'] / 'config.json').read_text())


@pytest.mark.skipif(sys.platform == 'win32', reason='path handling')
def test_default_config_dir_is_platform_and_xdg_appropriate(partial_config, monkeypatch):
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


@pytest.mark.skipif(sys.platform != 'win32', reason='path unhandling')
def test_default_config_dir_on_win32(partial_config, monkeypatch):
    assert Config(**partial_config).config_dir == Path.home() / 'AppData/Roaming/instawow'
    monkeypatch.delenv('APPDATA')
    assert Config(**partial_config).config_dir == Path.home() / 'instawow'
