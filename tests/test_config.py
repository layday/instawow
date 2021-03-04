from pathlib import Path
import sys

import pytest

from instawow.config import Config, Flavour


def test_env_vars_have_prio(iw_full_config, monkeypatch):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', '/foo')
    monkeypatch.setenv('INSTAWOW_GAME_FLAVOUR', 'classic')

    config = Config(**iw_full_config)
    assert config.config_dir == Path('/foo').resolve()
    assert config.game_flavour is Flavour.classic


def test_config_dir_is_populated(iw_full_config):
    config = Config(**iw_full_config).write()
    assert {i.name for i in config.profile_dir.iterdir()} == {'config.json', 'logs', 'plugins'}


def test_reading_missing_config_from_env_raises(iw_full_config, monkeypatch):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(iw_full_config['config_dir']))
    with pytest.raises(FileNotFoundError):
        Config.read('__default__')


@pytest.mark.skipif(sys.platform == 'win32', reason='no ~ expansion on Windows')
@pytest.mark.parametrize('folder', ['config_dir', 'addon_dir', 'temp_dir'])
def test_invalid_user_expansion_raises(monkeypatch, iw_full_config, folder):
    monkeypatch.delenv(f'INSTAWOW_{folder.upper()}', raising=False)
    with pytest.raises(ValueError):
        Config(**{**iw_full_config, folder: '~foo'})


def test_missing_addon_dir_raises(iw_full_config):
    with pytest.raises(ValueError):
        Config(**{**iw_full_config, 'addon_dir': 'foo'})


@pytest.mark.skipif(sys.platform == 'win32', reason='path handling')
def test_default_config_dir_is_platform_appropriate(iw_partial_config, monkeypatch):
    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'linux')
        config_dir = Config(**iw_partial_config).config_dir
        assert config_dir == Path.home() / '.config/instawow'

        patcher.setenv('XDG_CONFIG_HOME', '/foo')
        config_dir = Config(**iw_partial_config).config_dir
        assert config_dir == Path('/foo/instawow')

    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'darwin')
        config_dir = Config(**iw_partial_config).config_dir
        assert config_dir == Path.home() / 'Library/Application Support/instawow'


@pytest.mark.skipif(sys.platform != 'win32', reason='path unhandling')
def test_default_config_dir_is_win32_appropriate(iw_partial_config, monkeypatch):
    assert Config(**iw_partial_config).config_dir == Path.home() / 'AppData/Roaming/instawow'
    monkeypatch.delenv('APPDATA')
    assert Config(**iw_partial_config).config_dir == Path.home() / 'instawow'


def test_can_infer_flavour_from_path():
    assert Config.infer_flavour('wowzerz/_classic_/Interface/AddOns') is Flavour.classic
    assert Config.infer_flavour('/foo/bar/_classic_ptr_/Interface/AddOns') is Flavour.classic
    assert Config.infer_flavour('wowzerz/_retail_/Interface/AddOns') is Flavour.retail


def test_can_list_profiles(monkeypatch, iw_full_config):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(iw_full_config['config_dir']))
    assert Config.list_profiles() == []
    Config.parse_obj(iw_full_config).write()
    Config.parse_obj({**iw_full_config, 'profile': 'foo'}).write()
    assert sorted(Config.list_profiles()) == ['__default__', 'foo']


def test_can_delete_profile(iw_full_config):
    config = Config(**iw_full_config).write()
    assert config.profile_dir.exists()
    config.delete()
    assert not config.profile_dir.exists()
