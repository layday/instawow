
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

from instawow.config import Config
from instawow.exceptions import ConfigError


@pytest.fixture
def folders(tmp_path):
    config = tmp_path / 'config'
    addons = tmp_path / 'addons'
    addons.mkdir()
    return {'config_dir': config, 'addon_dir': addons}


def test_strs_are_coerced_to_paths(folders):
    config = Config(**{k: str(v) for k, v in folders.items()})
    assert config.config_dir == folders['config_dir']
    assert config.addon_dir == folders['addon_dir']


def test_env_vars_have_precedence_over_kwargs(folders, tmp_path):
    config1 = tmp_path / 'config1'
    with patch.dict(os.environ, {'INSTAWOW_CONFIG_DIR': str(config1)}):
        config = Config(**folders)
        assert config.config_dir == config1
        assert config.addon_dir == folders['addon_dir']


def test_config_dir_is_populated(folders):
    config = Config(**folders)
    config.write()
    config_paths = set(config.config_dir.iterdir())
    assert config_paths == {folders['config_dir'] / 'addon_dir.txt',
                            folders['config_dir'] / 'plugins'}


def test_nonexistent_addon_folder_is_rejected(folders, tmp_path):
    addons1 = tmp_path / 'addons1'
    with pytest.raises(ConfigError, match=f"'{addons1}' is not a directory"):
        Config(config_dir=folders['config_dir'], addon_dir=addons1)


def test_reading_addon_folder_from_uninstantiated_profile(folders):
    with pytest.raises(ConfigError, match='configuration not written on disk'):
        Config(config_dir=folders['config_dir'])


def test_reading_addon_folder_from_instantiated_profile(folders):
    Config(**folders).write()
    assert Config(config_dir=folders['config_dir']).addon_dir == folders['addon_dir']


def test_default_config_dir_is_xdg_compliant(folders):
    with patch('sys.platform', 'linux'):
        config_dir = Config(addon_dir=folders['addon_dir']).config_dir
        assert config_dir == Path.home() / '.config/instawow'

        with patch.dict(os.environ, {'XDG_CONFIG_HOME': '/foo'}):
            config_dir = Config(addon_dir=folders['addon_dir']).config_dir
            assert config_dir == Path('/foo/instawow')

    with patch('sys.platform', 'darwin'):
        config_dir = Config(addon_dir=folders['addon_dir']).config_dir
        assert config_dir == Path.home() / 'Library/Application Support/instawow'

        # with patch.dict(os.environ, {'XDG_CONFIG_HOME': 'foo'}):
        #     config_dir = Config(addon_dir=folders['addon_dir']).config_dir
        #     assert config_dir == Path('foo') / 'instawow'
