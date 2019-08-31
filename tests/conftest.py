
import pytest


@pytest.fixture
def simple_config(tmp_path):
    addons = tmp_path / 'addons'
    addons.mkdir()
    return {'addon_dir': addons, 'game_flavour': 'retail'}


@pytest.fixture
def full_config(tmp_path, simple_config):
    return {**simple_config, 'config_dir': tmp_path / 'config'}
