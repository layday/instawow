from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import cattrs
import pytest

from instawow.config import GlobalConfig, ProfileConfig, UninitialisedConfigError, make_plugin_dirs


def test_top_level_env_vars_take_precedence(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv('INSTAWOW_AUTO_UPDATE_CHECK', '1')
    global_config = GlobalConfig.from_values({'auto_update_check': False}, env=True)
    assert global_config.auto_update_check is True


def test_nested_env_vars_take_precedence(
    monkeypatch: pytest.MonkeyPatch,
):
    override = 'utter nonsense'
    monkeypatch.setenv('INSTAWOW_ACCESS_TOKENS_GITHUB', override)
    global_config = GlobalConfig.from_values({'access_tokens': {'github': 'true story'}}, env=True)
    assert global_config.access_tokens.github == override


def test_nested_env_var_objs_take_precedence(
    monkeypatch: pytest.MonkeyPatch,
):
    override = 'utter nonsense'
    monkeypatch.setenv('INSTAWOW_ACCESS_TOKENS', json.dumps({'github': override}))
    monkeypatch.setenv('INSTAWOW_ACCESS_TOKENS_GITHUB', 'true story')
    global_config = GlobalConfig.from_values(env=True)
    assert global_config.access_tokens.github == override


def test_nested_env_vars_loaded_when_values_absent(
    monkeypatch: pytest.MonkeyPatch,
):
    override = 'utter nonsense'
    monkeypatch.setenv('INSTAWOW_ACCESS_TOKENS_GITHUB', override)
    global_config = GlobalConfig.from_values(env=True)
    assert global_config.access_tokens.github == override


def test_read_profile_from_nonexistent_config_dir_raises():
    global_config = GlobalConfig()
    with pytest.raises(UninitialisedConfigError):
        ProfileConfig.read(global_config, '__default__')


def test_init_with_nonexistent_addon_dir_raises(
    iw_profile_config_values: dict[str, Any],
):
    global_config = GlobalConfig().write()
    with pytest.raises(cattrs.ClassValidationError) as exc_info:
        ProfileConfig.from_values(
            iw_profile_config_values | {'global_config': global_config, 'addon_dir': '#@$foo'}
        )
    assert exc_info.group_contains(ValueError, match='not a writable directory')


def test_default_config_dir(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv('INSTAWOW_HOME')
    monkeypatch.delenv('XDG_CONFIG_HOME', False)

    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'linux')

        assert GlobalConfig().dirs.config == Path.home() / '.config/instawow'

    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'darwin')

        assert GlobalConfig().dirs.config == Path.home() / 'Library/Application Support/instawow'

    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'win32')

        patcher.delenv('APPDATA', False)
        assert GlobalConfig().dirs.config == Path.home() / '.config' / 'instawow'

        patcher.setenv('APPDATA', '/foo')
        assert GlobalConfig().dirs.config == Path('/foo/instawow').resolve()


def test_default_state_dir(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv('INSTAWOW_HOME')
    monkeypatch.delenv('XDG_STATE_HOME', False)

    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'linux')

        assert GlobalConfig().dirs.state == Path.home() / '.local' / 'state' / 'instawow'

    for platform in {'darwin', 'win32'}:
        with monkeypatch.context() as patcher:
            patcher.setattr(sys, 'platform', platform)

            global_config = GlobalConfig()
            assert global_config.dirs.config == global_config.dirs.state


def test_default_cache_dir(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv('INSTAWOW_HOME')
    monkeypatch.delenv('XDG_CACHE_HOME', False)

    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'linux')

        assert GlobalConfig().dirs.cache == Path.home() / '.cache' / 'instawow'

    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'darwin')

        assert GlobalConfig().dirs.cache == Path.home() / 'Library/Caches/instawow'

    with monkeypatch.context() as patcher:
        patcher.setattr(sys, 'platform', 'win32')

        patcher.delenv('LOCALAPPDATA', False)
        assert GlobalConfig().dirs.cache == Path.home() / '.cache' / 'instawow'

        patcher.setenv('LOCALAPPDATA', '/foo')
        assert GlobalConfig().dirs.cache == Path('/foo/instawow').resolve()


def test_home_env_var_respected(
    iw_home: Path,
):
    global_config = GlobalConfig()
    assert global_config.dirs.config == iw_home / 'config'
    assert global_config.dirs.state == iw_home / 'state'
    assert global_config.dirs.cache == iw_home / 'cache'


def test_xdg_env_vars_respected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.delenv('INSTAWOW_HOME')

    x_homes = {c: tmp_path / f'iw_{c}_home' for c in ('config', 'state', 'cache')}
    for dir_name, path in x_homes.items():
        monkeypatch.setenv(f'XDG_{dir_name.upper()}_HOME', str(path))

    global_config = GlobalConfig()
    assert global_config.dirs.config == x_homes['config'] / 'instawow'
    assert global_config.dirs.state == x_homes['state'] / 'instawow'
    assert global_config.dirs.cache == x_homes['cache'] / 'instawow'


def test_plugin_dir_names():
    global_config_dirs = GlobalConfig().dirs
    plugin_dirs = make_plugin_dirs('foo')
    assert global_config_dirs.config / 'plugins' / 'foo' == plugin_dirs.config
    assert global_config_dirs.cache / 'plugins' / 'foo' == plugin_dirs.cache
    assert global_config_dirs.state / 'plugins' / 'foo' == plugin_dirs.state


def test_access_tokens_file_takes_precedence_over_config():
    global_config = GlobalConfig.read().write()
    assert global_config.access_tokens.cfcore is None
    global_config.dirs.config.joinpath('config.access_tokens.json').write_text(
        json.dumps({'cfcore': 'abc'}), encoding='utf-8'
    )
    assert GlobalConfig.read().access_tokens.cfcore == 'abc'


def test_can_list_profiles(
    iw_profile_config_values: dict[str, Any],
):
    global_config = GlobalConfig.read()
    assert set(ProfileConfig.iter_profiles(global_config)) == set()

    ProfileConfig.from_values(iw_profile_config_values | {'global_config': global_config}).write()
    ProfileConfig.from_values(
        iw_profile_config_values | {'global_config': global_config, 'profile': 'foo'}
    ).write()
    assert set(ProfileConfig.iter_profiles(global_config)) == {'__default__', 'foo'}


def test_can_list_installations(
    iw_profile_config_values: dict[str, Any],
):
    global_config = GlobalConfig.read()
    assert set(ProfileConfig.iter_profile_installations(global_config)) == set()

    ProfileConfig.from_values(iw_profile_config_values | {'global_config': global_config}).write()
    assert set(ProfileConfig.iter_profile_installations(global_config)) == {
        iw_profile_config_values['_installation_dir']
    }


def test_profile_dirs_populated(
    iw_profile_config_values: dict[str, Any],
):
    global_config = GlobalConfig()
    profile_config = ProfileConfig.from_values(
        iw_profile_config_values | {'global_config': global_config}
    ).write()
    assert {i.name for i in profile_config.config_path.iterdir()}.issuperset({'config.json'})


def test_can_delete_profile(
    iw_profile_config_values: dict[str, Any],
):
    global_config = GlobalConfig().write()
    profile_config = ProfileConfig.from_values(
        iw_profile_config_values | {'global_config': global_config}
    ).write()
    assert profile_config.config_path.exists()
    profile_config.delete()
    assert not profile_config.config_path.exists()


def test_profiled_name_validated(
    iw_profile_config_values: dict[str, Any],
):
    global_config = GlobalConfig()

    with pytest.raises(cattrs.ClassValidationError) as exc_info:
        ProfileConfig.from_values(
            iw_profile_config_values | {'global_config': global_config, 'profile': ''}
        )

    (value_error,) = exc_info.value.exceptions
    assert value_error.args == ('Value must have a minimum length of 1',)

    (note,) = value_error.__notes__
    assert note == 'Structuring class ProfileConfig @ attribute profile'
    assert type(note) is cattrs.AttributeValidationNote
    assert note.name == 'profile'


@pytest.mark.skipif(
    sys.platform == 'win32',
    reason='chmod has no effect on Windows',
)
def test_addon_dir_validated(
    tmp_path: Path,
    iw_profile_config_values: dict[str, Any],
):
    global_config = GlobalConfig()

    non_writeable_dir = tmp_path / 'non-writeable-dir'
    non_writeable_dir.mkdir(0o400)

    with pytest.raises(cattrs.ClassValidationError) as exc_info:
        ProfileConfig.from_values(
            iw_profile_config_values
            | {'global_config': global_config, 'addon_dir': non_writeable_dir}
        )

    (value_error,) = exc_info.value.exceptions
    assert value_error.args == (f'"{non_writeable_dir}" is not a writable directory',)

    (note,) = value_error.__notes__
    assert note == 'Structuring class ProfileConfig @ attribute addon_dir'
    assert type(note) is cattrs.AttributeValidationNote
    assert note.name == 'addon_dir'
