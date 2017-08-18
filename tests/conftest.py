
from pathlib import Path

import pytest
import vcr


@pytest.fixture(autouse=False,  # aiohttp support is kinda lacking, disabling for now
                scope='session')
def cassette():
    with vcr.use_cassette(str(Path(__file__).parent/'fixtures'/'cassette.yaml')):
        yield
