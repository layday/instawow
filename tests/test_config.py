from pathlib import Path
import sys

import pytest

from instawow.config import Config, Flavour


def test_env_vars_have_prio(iw_config_dict, monkeypatch):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', '/foo')
    monkeypatch.setenv('INSTAWOW_GAME_FLAVOUR', 'classic')

    config = Config(**iw_config_dict)
    assert config.config_dir == Path('/foo').resolve()
    assert config.game_flavour is Flavour.burning_crusade_classic


def test_config_dir_is_populated(iw_config_dict):
    config = Config(**iw_config_dict).write()
    assert {i.name for i in config.profile_dir.iterdir()} == {'config.json', 'logs', 'plugins'}


def test_reading_missing_config_from_env_raises(iw_config_dict, monkeypatch):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(iw_config_dict['config_dir']))
    with pytest.raises(FileNotFoundError):
        Config.read('__default__')


def test_missing_addon_dir_raises(iw_config_dict):
    with pytest.raises(ValueError):
        Config(**{**iw_config_dict, 'addon_dir': 'foo'})


@pytest.mark.skipif(sys.platform == 'win32', reason='path handling')
def test_default_config_dir_is_platform_appropriate(iw_config_dict_no_config_dir, monkeypatch):
    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'linux')
        config_dir = Config(**iw_config_dict_no_config_dir).config_dir
        assert config_dir == Path.home() / '.config/instawow'

        patcher.setenv('XDG_CONFIG_HOME', '/foo')
        config_dir = Config(**iw_config_dict_no_config_dir).config_dir
        assert config_dir == Path('/foo/instawow')

    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'darwin')
        config_dir = Config(**iw_config_dict_no_config_dir).config_dir
        assert config_dir == Path.home() / 'Library/Application Support/instawow'


@pytest.mark.skipif(sys.platform != 'win32', reason='path unhandling')
def test_default_config_dir_is_win32_appropriate(iw_config_dict_no_config_dir, monkeypatch):
    assert (
        Config(**iw_config_dict_no_config_dir).config_dir
        == Path.home() / 'AppData/Roaming/instawow'
    )
    monkeypatch.delenv('APPDATA')
    assert Config(**iw_config_dict_no_config_dir).config_dir == Path.home() / 'instawow'


def test_can_infer_flavour_from_path():
    assert (
        Config.infer_flavour('wowzerz/_classic_/Interface/AddOns')
        is Flavour.burning_crusade_classic
    )
    assert (
        Config.infer_flavour('/foo/bar/_classic_beta_/Interface/AddOns')
        is Flavour.burning_crusade_classic
    )
    assert (
        Config.infer_flavour('/foo/bar/_classic_ptr_/Interface/AddOns')
        is Flavour.burning_crusade_classic
    )
    assert Config.infer_flavour('_classic_era_/Interface/AddOns') is Flavour.vanilla_classic
    assert Config.infer_flavour('_classic_era_ptr_/Interface/AddOns') is Flavour.vanilla_classic
    assert Config.infer_flavour('wowzerz/_retail_/Interface/AddOns') is Flavour.retail
    assert Config.infer_flavour('anything goes') is Flavour.retail


def test_can_list_profiles(monkeypatch, iw_config_dict):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(iw_config_dict['config_dir']))
    assert Config.list_profiles() == []
    Config.parse_obj(iw_config_dict).write()
    Config.parse_obj({**iw_config_dict, 'profile': 'foo'}).write()
    assert sorted(Config.list_profiles()) == ['__default__', 'foo']


def test_can_delete_profile(iw_config_dict):
    config = Config(**iw_config_dict).write()
    assert config.profile_dir.exists()
    config.delete()
    assert not config.profile_dir.exists()
