from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pytest

from instawow.common import Flavour
from instawow.config import Config, GlobalConfig


def test_env_vars_have_prio(
    monkeypatch: pytest.MonkeyPatch,
    iw_global_config_values: dict[str, Any],
    iw_config_values: dict[str, Any],
):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', '/foo')
    monkeypatch.setenv('INSTAWOW_GAME_FLAVOUR', 'classic')

    global_config = GlobalConfig(**iw_global_config_values)
    config = Config(global_config=global_config, **iw_config_values)

    assert global_config.config_dir == Path('/foo').resolve()
    assert config.game_flavour is Flavour.burning_crusade_classic


def test_config_dir_is_populated(
    iw_global_config_values: dict[str, Any],
    iw_config_values: dict[str, Any],
):
    global_config = GlobalConfig(**iw_global_config_values)
    config = Config(global_config=global_config, **iw_config_values).write()
    assert {i.name for i in config.profile_dir.iterdir()} == {'config.json', 'logs', 'plugins'}


def test_read_profile_from_nonexistent_config_dir_raises(
    iw_global_config_values: dict[str, Any],
):
    global_config = GlobalConfig(config_dir=iw_global_config_values['config_dir'])
    with pytest.raises(FileNotFoundError):
        Config.read(global_config, '__default__')


def test_init_with_nonexistent_addon_dir_raises(
    iw_global_config_values: dict[str, Any],
    iw_config_values: dict[str, Any],
):
    global_config = GlobalConfig(**iw_global_config_values).write()
    with pytest.raises(ValueError, match='not a writable directory'):
        Config(global_config=global_config, **{**iw_config_values, 'addon_dir': 'foo'})


@pytest.mark.skipif(
    sys.platform == 'win32',
    reason='requires absence of platform-specific env var',
)
def test_default_config_dir_is_platform_appropriate(
    monkeypatch: pytest.MonkeyPatch,
):
    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'linux')
        config_dir = GlobalConfig().config_dir
        assert config_dir == Path.home() / '.config/instawow'

        patcher.setenv('XDG_CONFIG_HOME', '/foo')
        config_dir = GlobalConfig().config_dir
        assert config_dir == Path('/foo/instawow')

    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'darwin')
        config_dir = GlobalConfig().config_dir
        assert config_dir == Path.home() / 'Library/Application Support/instawow'


@pytest.mark.skipif(
    sys.platform != 'win32',
    reason='requires presence of platform-specific env var',
)
def test_default_config_dir_is_unplatform_appropriate(
    monkeypatch: pytest.MonkeyPatch,
):
    assert GlobalConfig().config_dir == Path.home() / 'AppData/Roaming/instawow'
    monkeypatch.delenv('APPDATA')
    assert GlobalConfig().config_dir == Path.home() / 'instawow'


def test_can_infer_flavour_from_path():
    infer = Config.infer_flavour
    assert infer('wowzerz/_classic_/Interface/AddOns') is Flavour.burning_crusade_classic
    assert infer('/foo/bar/_classic_beta_/Interface/AddOns') is Flavour.burning_crusade_classic
    assert infer('/foo/bar/_classic_ptr_/Interface/AddOns') is Flavour.burning_crusade_classic
    assert infer('_classic_era_/Interface/AddOns') is Flavour.vanilla_classic
    assert infer('_classic_era_ptr_/Interface/AddOns') is Flavour.vanilla_classic
    assert infer('wowzerz/_retail_/Interface/AddOns') is Flavour.retail
    assert infer('anything goes') is Flavour.retail


def test_can_list_profiles(
    monkeypatch: pytest.MonkeyPatch,
    iw_global_config_values: dict[str, Any],
    iw_config_values: dict[str, Any],
):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(iw_global_config_values['config_dir']))

    global_config = GlobalConfig()
    assert global_config.list_profiles() == []

    Config(global_config=global_config, **iw_config_values).write()
    Config(global_config=global_config, **{**iw_config_values, 'profile': 'foo'}).write()
    assert set(global_config.list_profiles()) == {'__default__', 'foo'}


def test_can_delete_profile(
    iw_global_config_values: dict[str, Any],
    iw_config_values: dict[str, Any],
):
    global_config = GlobalConfig(**iw_global_config_values).write()
    config = Config(global_config=global_config, **iw_config_values).write()
    assert config.profile_dir.exists()
    config.delete()
    assert not config.profile_dir.exists()


def test_can_omit_global_config(
    monkeypatch: pytest.MonkeyPatch,
    iw_global_config_values: dict[str, Any],
    iw_config_values: dict[str, Any],
):
    global_config = GlobalConfig(**iw_global_config_values)
    Config(global_config=global_config, **iw_config_values).write()

    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(iw_global_config_values['config_dir']))
    config = Config.read(None, iw_config_values['profile'])
    assert config.global_config.dict() == global_config.dict()
