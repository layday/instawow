import enum
from functools import partial
import json
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner
import pytest

from instawow.cli import main
from instawow.config import Config
from instawow.manager import CliManager, prepare_db_session


class Flavour(enum.IntEnum):
    retail = enum.auto()
    classic = enum.auto()


@pytest.fixture(params=['retail', 'classic'])
def full_config(tmp_path_factory, request, temp_dir):
    name = f'{request.node.name[: request.node.name.index("[")]}_{request.param}'
    parametrized_tmp_path = tmp_path_factory.getbasetemp() / name
    addons = parametrized_tmp_path / 'addons'
    addons.mkdir(parents=True, exist_ok=True)

    return {
        '_parametrized_tmp_path': parametrized_tmp_path,
        'config_dir': parametrized_tmp_path / 'config',
        'addon_dir': addons,
        'temp_dir': temp_dir,
        'game_flavour': request.param,
    }


@pytest.fixture
def manager(event_loop, web_client, full_config):
    config = Config(**full_config).write()
    db_session = prepare_db_session(config=config)

    manager = CliManager(config, db_session)
    manager.run = event_loop.run_until_complete
    manager.web_client = web_client
    yield manager


@pytest.fixture
def run(request, manager):
    param = getattr(request, 'param', None)
    if param is Flavour.retail and manager.config.is_classic:
        pytest.skip('test is for retail only')
    elif param is Flavour.classic and manager.config.is_retail:
        pytest.skip('test is for classic only')

    yield partial(CliRunner().invoke, main, obj=SimpleNamespace(m=manager))


@pytest.fixture
def molinari_and_run(run):
    run('install curse:molinari')
    yield run


@pytest.mark.parametrize(
    'inp, cmp',
    [
        ('install curse:molinari', lambda v: v.startswith('✓ curse:molinari\n  installed')),
        ('install curse:molinari', '✗ curse:molinari\n  package already installed\n'.__eq__),
        ('update curse:molinari', '✗ curse:molinari\n  package is up to date\n'.__eq__),
        ('remove curse:molinari', '✓ curse:molinari\n  removed\n'.__eq__),
        ('update curse:molinari', '✗ curse:molinari\n  package is not installed\n'.__eq__),
        ('remove curse:molinari', '✗ curse:molinari\n  package is not installed\n'.__eq__),
    ],
)
def test_valid_curse_pkg_lifecycle(run, inp, cmp):
    assert cmp(run(inp).output)


@pytest.mark.parametrize(
    'inp, cmp, run',
    [
        ('install tukui:1', lambda v: v.startswith('✓ tukui:1\n  installed'), None),
        ('install tukui:1', '✗ tukui:1\n  package already installed\n'.__eq__, None),
        (
            'update tukui:1',
            '✗ tukui:1-merathilisui\n  package is up to date\n'.__eq__,
            Flavour.retail,
        ),
        (
            'update tukui:1',
            '✗ tukui:1-tukui\n  package is up to date\n'.__eq__,
            Flavour.classic,
        ),
        ('remove tukui:1', '✓ tukui:1\n  removed\n'.__eq__, None),
        ('update tukui:1', '✗ tukui:1\n  package is not installed\n'.__eq__, None),
        ('remove tukui:1', '✗ tukui:1\n  package is not installed\n'.__eq__, None),
        (
            'install tukui:tukui',
            lambda v: v.startswith('✓ tukui:tukui\n  installed'),
            Flavour.retail,
        ),
        (
            'install tukui:tukui',
            '✗ tukui:tukui\n  package already installed\n'.__eq__,
            Flavour.retail,
        ),
        ('update tukui:tukui', '✗ tukui:tukui\n  package is up to date\n'.__eq__, Flavour.retail),
        ('remove tukui:tukui', '✓ tukui:tukui\n  removed\n'.__eq__, Flavour.retail),
        (
            'install tukui:tukui',
            '✗ tukui:tukui\n  package does not exist\n'.__eq__,
            Flavour.classic,
        ),
        ('update tukui:tukui', '✗ tukui:tukui\n  package is not installed\n'.__eq__, None),
        ('remove tukui:tukui', '✗ tukui:tukui\n  package is not installed\n'.__eq__, None),
    ],
    indirect=('run',),
)
def test_valid_tukui_pkg_lifecycle(run, inp, cmp):
    assert cmp(run(inp).output)


@pytest.mark.parametrize(
    'inp, cmp',
    [
        (
            'install wowi:13188-molinari',
            lambda v: v.startswith('✓ wowi:13188-molinari\n  installed'),
        ),
        (
            'install wowi:13188-molinari',
            '✗ wowi:13188-molinari\n  package already installed\n'.__eq__,
        ),
        ('update wowi:13188-molinari', '✗ wowi:13188-molinari\n  package is up to date\n'.__eq__),
        ('remove wowi:13188-molinari', '✓ wowi:13188-molinari\n  removed\n'.__eq__),
        (
            'update wowi:13188-molinari',
            '✗ wowi:13188-molinari\n  package is not installed\n'.__eq__,
        ),
        (
            'remove wowi:13188-molinari',
            '✗ wowi:13188-molinari\n  package is not installed\n'.__eq__,
        ),
    ],
)
def test_valid_wowi_pkg_lifecycle(run, inp, cmp):
    assert cmp(run(inp).output)


@pytest.mark.parametrize(
    'inp, cmp, run',
    [
        (
            'install curse:molinari',
            lambda v: v.startswith('✓ curse:molinari\n  installed'),
            Flavour.retail,
        ),
        (
            'install wowi:13188-molinari',
            "✗ wowi:13188-molinari\n"
            "  package folders conflict with installed package curse:molinari\n".__eq__,
            Flavour.retail,
        ),
        ('remove curse:molinari', '✓ curse:molinari\n  removed\n'.__eq__, Flavour.retail),
    ],
    indirect=('run',),
)
def test_folder_conflict_lifecycle(run, inp, cmp):
    assert cmp(run(inp).output)


def test_preexisting_folder_conflict_on_install(manager, run):
    manager.config.addon_dir.joinpath('Molinari').mkdir()
    assert (
        run('install curse:molinari').output
        == '''\
✗ curse:molinari
  package folders conflict with 'Molinari'
'''
    )
    assert run('install -o curse:molinari').output.startswith('✓ curse:molinari\n  installed')


@pytest.mark.parametrize(
    'inp, output',
    [
        ('install curse:gargantuan-wigs', '✗ curse:gargantuan-wigs\n  package does not exist\n'),
        ('update curse:gargantuan-wigs', '✗ curse:gargantuan-wigs\n  package is not installed\n'),
        ('remove curse:gargantuan-wigs', '✗ curse:gargantuan-wigs\n  package is not installed\n'),
    ],
)
def test_invalid_addon_name_lifecycle(run, inp, output):
    assert run(inp).output == output


@pytest.mark.parametrize(
    'inp, output',
    [
        ('install foo:bar', '✗ foo:bar\n  package source is invalid\n'),
        ('update foo:bar', '✗ foo:bar\n  package is not installed\n'),
        ('remove foo:bar', '✗ foo:bar\n  package is not installed\n'),
    ],
)
def test_invalid_source_lifecycle(run, inp, output):
    assert run(inp).output == output


@pytest.mark.parametrize(
    'inp, cmp',
    [
        ('install curse:molinari', lambda v: v.startswith('✓ curse:molinari\n  installed')),
        ('install curse:20338', '✗ curse:20338\n  package already installed\n'.__eq__),
        (
            'install https://www.wowace.com/projects/molinari',
            '✗ curse:molinari\n  package already installed\n'.__eq__,
        ),
        (
            'install https://www.curseforge.com/wow/addons/molinari',
            '✗ curse:molinari\n  package already installed\n'.__eq__,
        ),
        (
            'install https://www.curseforge.com/wow/addons/molinari/download',
            '✗ curse:molinari\n  package already installed\n'.__eq__,
        ),
        ('remove curse:molinari', '✓ curse:molinari\n  removed\n'.__eq__),
    ],
)
def test_install_with_curse_alias(run, inp, cmp):
    assert cmp(run(inp).output)


@pytest.mark.parametrize(
    'inp, cmp, run',
    [
        ('install tukui:-1', lambda v: v.startswith('✓ tukui:-1\n  installed'), Flavour.retail),
        ('install tukui:-1', '✗ tukui:-1\n  package does not exist\n'.__eq__, Flavour.classic),
        (
            'install tukui:tukui',
            '✗ tukui:tukui\n  package already installed\n'.__eq__,
            Flavour.retail,
        ),
        (
            'install tukui:tukui',
            '✗ tukui:tukui\n  package does not exist\n'.__eq__,
            Flavour.classic,
        ),
        (
            'install https://www.tukui.org/download.php?ui=tukui',
            '✗ tukui:tukui\n  package already installed\n'.__eq__,
            Flavour.retail,
        ),
        (
            'install https://www.tukui.org/download.php?ui=tukui',
            '✗ tukui:tukui\n  package does not exist\n'.__eq__,
            Flavour.classic,
        ),
        (
            'install https://www.tukui.org/addons.php?id=1',
            lambda v: v.startswith('✓ tukui:1\n  installed'),
            None,
        ),
        ('install tukui:1', '✗ tukui:1\n  package already installed\n'.__eq__, None),
        ('remove tukui:1', '✓ tukui:1\n  removed\n'.__eq__, None),
    ],
    indirect=('run',),
)
def test_install_with_tukui_alias(run, inp, cmp):
    assert cmp(run(inp).output)


@pytest.mark.parametrize(
    'inp, cmp',
    [
        ('install wowi:13188', lambda v: v.startswith('✓ wowi:13188\n  installed')),
        (
            'install wowi:13188-molinari',
            '✗ wowi:13188-molinari\n  package already installed\n'.__eq__,
        ),
        (
            'install https://www.wowinterface.com/downloads/landing.php?fileid=13188',
            '✗ wowi:13188\n  package already installed\n'.__eq__,
        ),
        (
            'install https://www.wowinterface.com/downloads/fileinfo.php?id=13188',
            '✗ wowi:13188\n  package already installed\n'.__eq__,
        ),
        (
            'install https://www.wowinterface.com/downloads/download13188-Molinari',
            '✗ wowi:13188\n  package already installed\n'.__eq__,
        ),
        (
            'install https://www.wowinterface.com/downloads/info13188-Molinari.html',
            '✗ wowi:13188\n  package already installed\n'.__eq__,
        ),
        ('remove wowi:13188', '✓ wowi:13188\n  removed\n'.__eq__),
    ],
)
def test_install_with_wowi_alias(run, inp, cmp):
    assert cmp(run(inp).output)


def test_missing_dir_on_remove(manager, molinari_and_run):
    addon_dir = manager.config.addon_dir
    addon_dir.joinpath('Molinari').rename(addon_dir.joinpath('NotMolinari'))
    assert molinari_and_run('remove curse:molinari').output == '✓ curse:molinari\n  removed\n'


@pytest.mark.parametrize(
    'command, exit_code',
    [
        ('list mol', 0),
        ('info foo', 0),
        ('visit mol', 0),
        ('visit foo', 1),
        ('reveal mol', 0),
        ('reveal foo', 1),
    ],
)
@patch('webbrowser.open', lambda v: ...)
def test_exit_codes_with_substr_match(molinari_and_run, command, exit_code):
    assert molinari_and_run(command).exit_code == exit_code


def test_substr_list_match(molinari_and_run):
    assert molinari_and_run('list mol').output == 'curse:molinari\n'
    assert molinari_and_run('list foo').output == ''
    assert molinari_and_run('list -f detailed mol').output.startswith('curse:molinari')
    (molinari,) = json.loads(molinari_and_run('list -f json mol').output)
    assert (molinari['source'], molinari['slug']) == ('curse', 'molinari')


def test_csv_export_and_import(molinari_and_run, manager):
    export_csv = manager.config._parametrized_tmp_path / 'export.csv'
    molinari_and_run(f'list -e "{export_csv}"')

    assert (
        export_csv.read_text(encoding='utf-8')
        == '''\
defn,strategy
curse:molinari,default
'''
    )
    assert (
        molinari_and_run(f'install -i "{export_csv}"').output
        == '''\
✗ curse:molinari
  package already installed
'''
    )
