from filecmp import dircmp
from pathlib import Path
from shutil import move
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
    assert {i.name for i in config.profile_dir.iterdir()} == {'config.json', 'logs', 'plugins'}


def test_reading_missing_config_from_env_raises(full_config, monkeypatch):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(full_config['config_dir']))
    with pytest.raises(FileNotFoundError):
        Config.read('__default__')


@pytest.mark.skipif(sys.platform == 'win32', reason='no ~ expansion on Windows')
@pytest.mark.parametrize('dir_', ['config_dir', 'addon_dir', 'temp_dir'])
def test_invalid_user_expansion_raises(full_config, dir_):
    with pytest.raises(ValueError):
        Config(**{**full_config, dir_: '~foo'})


def test_missing_addon_dir_raises(full_config):
    with pytest.raises(ValueError):
        Config(**{**full_config, 'addon_dir': 'foo'})


@pytest.mark.skipif(sys.platform == 'win32', reason='path handling')
def test_default_config_dir_is_platform_appropriate(partial_config, monkeypatch):
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
def test_default_config_dir_is_win32_appropriate(partial_config, monkeypatch):
    assert Config(**partial_config).config_dir == Path.home() / 'AppData/Roaming/instawow'
    monkeypatch.delenv('APPDATA')
    assert Config(**partial_config).config_dir == Path.home() / 'instawow'


def test_legacy_profile_migration_goes_swimmingly(full_config, monkeypatch):
    legacy_config = Config(**full_config).write()
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(full_config['config_dir']))

    comparison = dircmp(legacy_config.config_dir, legacy_config.profile_dir)
    profile_dirs = sorted(i.name for i in legacy_config.profile_dir.iterdir())
    assert comparison.common == []
    assert comparison.left_list == ['profiles']
    assert sorted(comparison.right_list) == profile_dirs

    for name in profile_dirs:
        move(str(legacy_config.profile_dir / name), legacy_config.config_dir / name)
    legacy_config.profile_dir.rmdir()
    Config.get_dummy_config(config_dir=full_config['config_dir']).read('__default__')

    comparison = dircmp(legacy_config.config_dir, legacy_config.profile_dir)
    assert comparison.common == []
    assert comparison.left_list == ['profiles']
    assert sorted(comparison.right_list) == profile_dirs
