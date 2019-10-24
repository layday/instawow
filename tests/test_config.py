import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from instawow.config import Config


def test_strs_are_coerced_to_paths(full_config):
    config = Config(**{k: str(v) for k, v in full_config.items()})
    assert config.config_dir == full_config['config_dir']
    assert config.addon_dir == full_config['addon_dir']
    assert config.temp_dir == full_config['temp_dir']


def test_env_vars_have_prio(full_config, tmp_path):
    config1 = tmp_path / 'config1'
    flavour = 'classic'
    env_overrides = {'INSTAWOW_CONFIG_DIR': str(config1), 'INSTAWOW_GAME_FLAVOUR': flavour}
    with patch.dict(os.environ, env_overrides):
        config = Config(**full_config)
        assert config.config_dir == config1
        assert config.game_flavour == flavour


def test_config_dir_is_populated(full_config):
    config = Config(**full_config).write()
    assert {i.name for i in config.config_dir.iterdir()} == {'config.json', 'logs', 'plugins'}


def test_reading_config_missing(full_config):
    with patch.dict(os.environ, {'INSTAWOW_CONFIG_DIR': str(full_config['config_dir'])}):
        with pytest.raises(FileNotFoundError):
                Config.read()


def test_reading_config_existing(full_config):
    config = Config(**full_config).write()
    config_json = {'addon_dir': str(full_config['addon_dir']),
                   'temp_dir': str(full_config['temp_dir']),
                   'game_flavour': config.game_flavour}
    assert config_json == json.loads((full_config['config_dir'] / 'config.json').read_text())


def test_default_config_dir_is_xdg_compliant(partial_config):
    with patch('sys.platform', 'linux'):
        config_dir = Config(**partial_config).config_dir
        assert config_dir == Path.home() / '.config/instawow'

        with patch.dict(os.environ, {'XDG_CONFIG_HOME': '/foo'}):
            config_dir = Config(**partial_config).config_dir
            assert config_dir == Path('/foo/instawow')

    with patch('sys.platform', 'darwin'):
        config_dir = Config(**partial_config).config_dir
        assert config_dir == Path.home() / 'Library/Application Support/instawow'

        # with patch.dict(os.environ, {'XDG_CONFIG_HOME': 'foo'}):
        #     config_dir = Config(**partial_config).config_dir
        #     assert config_dir == Path('foo') / 'instawow'
