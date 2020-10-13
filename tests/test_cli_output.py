import enum
from functools import partial
import json

from click.testing import CliRunner
import pytest

from instawow import cli, config, utils


class Flavour(enum.IntEnum):
    retail = enum.auto()
    classic = enum.auto()


@pytest.fixture(autouse=True)
def mock(mock_all):
    pass


@pytest.fixture(params=list(Flavour.__members__))
def cli_config(
    request,
    tmp_path_factory,
):
    "Reuse the temporary folder for all cases of a parametrized test."
    parametrized_tmp_path = (
        tmp_path_factory.getbasetemp()
        / f'{request.node.name[: request.node.name.index("[")]}_{request.param}'
    )
    parametrized_tmp_path.mkdir(exist_ok=True)
    addon_dir = parametrized_tmp_path / 'addons'
    addon_dir.mkdir(exist_ok=True)
    return config.Config(
        config_dir=parametrized_tmp_path / 'config',
        addon_dir=addon_dir,
        game_flavour=request.param,
    ).write()


@pytest.fixture
def run(
    monkeypatch,
    request,
    event_loop,
    cli_config,
):
    param = getattr(request, 'param', None)
    if param is Flavour.retail and cli_config.is_classic:
        pytest.skip('test is for retail only')
    elif param is Flavour.classic and cli_config.is_retail:
        pytest.skip('test is for classic only')

    monkeypatch.setattr('instawow.manager.CliManager.run', event_loop.run_until_complete)
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(cli_config.config_dir))
    yield partial(
        CliRunner().invoke,
        cli.main,
        catch_exceptions=False,
    )


@pytest.fixture
def molinari_and_run(run):
    run('install curse:molinari')
    yield run


@pytest.mark.parametrize(
    'args, cmp',
    [
        (
            'install curse:molinari',
            lambda v: v.startswith('✓ curse:molinari\n  installed'),
        ),
        (
            'install curse:molinari',
            '✗ curse:molinari\n  package already installed\n'.__eq__,
        ),
        (
            'update curse:molinari',
            '✗ curse:molinari\n  package is up to date\n'.__eq__,
        ),
        (
            'remove curse:molinari',
            '✓ curse:molinari\n  removed\n'.__eq__,
        ),
        (
            'update curse:molinari',
            '✗ curse:molinari\n  package is not installed\n'.__eq__,
        ),
        (
            'remove curse:molinari',
            '✗ curse:molinari\n  package is not installed\n'.__eq__,
        ),
    ],
)
def test_valid_curse_pkg_lifecycle(run, args, cmp):
    assert cmp(run(args).output)


@pytest.mark.parametrize(
    'args, cmp, run',
    [
        (
            'install tukui:1',
            lambda v: v.startswith('✓ tukui:1\n  installed'),
            None,
        ),
        (
            'install tukui:1',
            '✗ tukui:1\n  package already installed\n'.__eq__,
            None,
        ),
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
        (
            'remove tukui:1',
            '✓ tukui:1\n  removed\n'.__eq__,
            None,
        ),
        (
            'update tukui:1',
            '✗ tukui:1\n  package is not installed\n'.__eq__,
            None,
        ),
        (
            'remove tukui:1',
            '✗ tukui:1\n  package is not installed\n'.__eq__,
            None,
        ),
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
        (
            'update tukui:tukui',
            '✗ tukui:tukui\n  package is up to date\n'.__eq__,
            Flavour.retail,
        ),
        (
            'remove tukui:tukui',
            '✓ tukui:tukui\n  removed\n'.__eq__,
            Flavour.retail,
        ),
        (
            'install tukui:tukui',
            '✗ tukui:tukui\n  package does not exist\n'.__eq__,
            Flavour.classic,
        ),
        (
            'update tukui:tukui',
            '✗ tukui:tukui\n  package is not installed\n'.__eq__,
            None,
        ),
        (
            'remove tukui:tukui',
            '✗ tukui:tukui\n  package is not installed\n'.__eq__,
            None,
        ),
    ],
    indirect=('run',),
)
def test_valid_tukui_pkg_lifecycle(run, args, cmp):
    assert cmp(run(args).output)


@pytest.mark.parametrize(
    'args, cmp',
    [
        (
            'install wowi:13188-molinari',
            lambda v: v.startswith('✓ wowi:13188-molinari\n  installed'),
        ),
        (
            'install wowi:13188-molinari',
            '✗ wowi:13188-molinari\n  package already installed\n'.__eq__,
        ),
        (
            'update wowi:13188-molinari',
            '✗ wowi:13188-molinari\n  package is up to date\n'.__eq__,
        ),
        (
            'remove wowi:13188-molinari',
            '✓ wowi:13188-molinari\n  removed\n'.__eq__,
        ),
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
def test_valid_wowi_pkg_lifecycle(run, args, cmp):
    assert cmp(run(args).output)


@pytest.mark.parametrize(
    'args, cmp, run',
    [
        (
            'install curse:molinari',
            lambda v: v.startswith('✓ curse:molinari\n  installed'),
            Flavour.retail,
        ),
        (
            'install wowi:13188-molinari',
            '✗ wowi:13188-molinari\n'
            '  package folders conflict with installed package Molinari\n'
            '    (curse:20338)\n'.__eq__,
            Flavour.retail,
        ),
        (
            'remove curse:molinari',
            '✓ curse:molinari\n  removed\n'.__eq__,
            Flavour.retail,
        ),
    ],
    indirect=('run',),
)
def test_folder_conflict_lifecycle(run, args, cmp):
    assert cmp(run(args).output)


def test_preexisting_folder_conflict_on_install(cli_config, run):
    cli_config.addon_dir.joinpath('Molinari').mkdir()
    assert (
        run('install curse:molinari').output
        == '''\
✗ curse:molinari
  package folders conflict with 'Molinari'
'''
    )
    assert run('install --replace curse:molinari').output.startswith(
        '✓ curse:molinari\n  installed'
    )


@pytest.mark.parametrize(
    'args, output',
    [
        (
            'install curse:gargantuan-wigs',
            '✗ curse:gargantuan-wigs\n  package does not exist\n',
        ),
        (
            'update curse:gargantuan-wigs',
            '✗ curse:gargantuan-wigs\n  package is not installed\n',
        ),
        (
            'remove curse:gargantuan-wigs',
            '✗ curse:gargantuan-wigs\n  package is not installed\n',
        ),
    ],
)
def test_invalid_addon_name_lifecycle(run, args, output):
    assert run(args).output == output


@pytest.mark.parametrize(
    'args, output',
    [
        (
            'install foo:bar',
            '✗ foo:bar\n  package source is invalid\n',
        ),
        (
            'update foo:bar',
            '✗ foo:bar\n  package is not installed\n',
        ),
        (
            'remove foo:bar',
            '✗ foo:bar\n  package is not installed\n',
        ),
    ],
)
def test_invalid_source_lifecycle(run, args, output):
    assert run(args).output == output


@pytest.mark.parametrize(
    'args, cmp',
    [
        (
            'install curse:molinari',
            lambda v: v.startswith('✓ curse:molinari\n  installed'),
        ),
        (
            'install curse:20338',
            '✗ curse:20338\n  package already installed\n'.__eq__,
        ),
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
        (
            'remove curse:molinari',
            '✓ curse:molinari\n  removed\n'.__eq__,
        ),
    ],
)
def test_install_with_curse_alias(run, args, cmp):
    assert cmp(run(args).output)


@pytest.mark.parametrize(
    'args, cmp, run',
    [
        (
            'install tukui:-1',
            lambda v: v.startswith('✓ tukui:-1\n  installed'),
            Flavour.retail,
        ),
        (
            'install tukui:-1',
            '✗ tukui:-1\n  package does not exist\n'.__eq__,
            Flavour.classic,
        ),
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
        (
            'install tukui:1',
            '✗ tukui:1\n  package already installed\n'.__eq__,
            None,
        ),
        (
            'remove tukui:1',
            '✓ tukui:1\n  removed\n'.__eq__,
            None,
        ),
    ],
    indirect=('run',),
)
def test_install_with_tukui_alias(run, args, cmp):
    assert cmp(run(args).output)


@pytest.mark.parametrize(
    'args, cmp',
    [
        (
            'install wowi:13188',
            lambda v: v.startswith('✓ wowi:13188\n  installed'),
        ),
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
        (
            'remove wowi:13188',
            '✓ wowi:13188\n  removed\n'.__eq__,
        ),
    ],
)
def test_install_with_wowi_alias(run, args, cmp):
    assert cmp(run(args).output)


@pytest.mark.parametrize(
    'args, cmp',
    [
        (
            'install github:AdiAddons/AdiButtonAuras',
            lambda v: v.startswith('✓ github:AdiAddons/AdiButtonAuras\n  installed'),
        ),
        (
            'install github:adiaddons/adibuttonauras',
            '✗ github:adiaddons/adibuttonauras\n  package already installed\n'.__eq__,
        ),
        (
            'install https://github.com/AdiAddons/AdiButtonAuras',
            '✗ github:AdiAddons/AdiButtonAuras\n  package already installed\n'.__eq__,
        ),
        (
            'install https://github.com/AdiAddons/AdiButtonAuras/releases',
            '✗ github:AdiAddons/AdiButtonAuras\n  package already installed\n'.__eq__,
        ),
        (
            'remove github:adiaddons/adibuttonauras',
            '✓ github:adiaddons/adibuttonauras\n  removed\n'.__eq__,
        ),
    ],
)
def test_install_with_github_alias(run, args, cmp):
    assert cmp(run(args).output)


@pytest.mark.parametrize(
    'args, output, run',
    [
        (
            'install curse:molinari',
            '✓ curse:molinari\n  installed 80300.66-Release\n',
            None,
        ),
        (
            'install --version foo curse:molinari',
            '✗ curse:molinari\n  package already installed\n',
            None,
        ),
        (
            'update curse:molinari',
            '✗ curse:molinari\n  package is up to date\n',
            None,
        ),
        (
            'remove curse:molinari',
            '✓ curse:molinari\n  removed\n',
            None,
        ),
        (
            'install --version foo curse:molinari',
            "✗ curse:molinari\n  no files compatible with retail using 'version' strategy\n",
            Flavour.retail,
        ),
        (
            'install --version foo curse:molinari',
            "✗ curse:molinari\n  no files compatible with classic using 'version' strategy\n",
            Flavour.classic,
        ),
        (
            'install --version 80000.57-Release curse:molinari',
            '✓ curse:molinari\n  installed 80000.57-Release\n',
            None,
        ),
        (
            'update curse:molinari',
            '✗ curse:molinari\n  package is pinned\n',
            None,
        ),
        (
            'remove curse:molinari',
            '✓ curse:molinari\n  removed\n',
            None,
        ),
    ],
    indirect=('run',),
)
def test_version_strategy_lifecycle(run, args, output):
    assert run(args).output == output


def test_install_sandwich(run):
    assert (
        run(
            'install'
            ' curse:molinari'
            ' -s latest curse:molinari'
            ' --version 80000.57-Release curse:molinari'
        ).output
        == '''\
✓ curse:molinari
  installed 80300.66-Release
✗ curse:molinari
  package folders conflict with installed package Molinari
    (curse:20338)
✗ curse:molinari
  package folders conflict with installed package Molinari
    (curse:20338)
'''
    )


def test_install_sandwich_defn_order_is_respected(run):
    assert (
        run(
            'install'
            ' --version 80000.57-Release curse:molinari'
            ' -s latest curse:molinari'
            ' curse:molinari'
        ).output
        == '''\
✓ curse:molinari
  installed 80000.57-Release
✗ curse:molinari
  package folders conflict with installed package Molinari
    (curse:20338)
✗ curse:molinari
  package folders conflict with installed package Molinari
    (curse:20338)
'''
    )


def test_install_sandwich_addon_argument_is_not_required(run):
    assert (
        run('install -s latest curse:molinari --version 80000.57-Release curse:molinari').output
        == '''\
✓ curse:molinari
  installed 80300.66-Release
✗ curse:molinari
  package folders conflict with installed package Molinari
    (curse:20338)
'''
    )


def test_addon_is_removed_even_if_folders_missing(cli_config, molinari_and_run):
    cli_config.addon_dir.joinpath('Molinari').rename(cli_config.addon_dir.joinpath('NotMolinari'))
    assert {cli_config.addon_dir.joinpath('NotMolinari')} == set(cli_config.addon_dir.iterdir())
    assert molinari_and_run('remove curse:molinari').output == '✓ curse:molinari\n  removed\n'


@pytest.mark.parametrize(
    'command, exit_code',
    [
        ('list mol', 0),
        ('info foo', 0),
        ('reveal mol', 0),
        ('reveal foo', 1),
    ],
)
def test_exit_codes_with_substr_match(monkeypatch, molinari_and_run, command, exit_code):
    monkeypatch.setattr('webbrowser.open', lambda v: ...)
    assert molinari_and_run(command).exit_code == exit_code


def test_can_list_with_substr_match(molinari_and_run):
    assert molinari_and_run('list mol').output == 'curse:molinari\n'
    assert molinari_and_run('list foo').output == ''
    assert molinari_and_run('list -f detailed mol').output.startswith('curse:molinari')
    (molinari,) = json.loads(molinari_and_run('list -f json mol').output)
    assert (molinari['source'], molinari['slug']) == ('curse', 'molinari')


def test_json_export_and_import(cli_config, molinari_and_run):
    export_json = cli_config.config_dir.parent / 'export.json'
    export_json.write_text(molinari_and_run('list -f json').output, encoding='utf-8')
    assert (
        molinari_and_run(f'install --import "{export_json}"').output
        == '✗ curse:molinari\n  package already installed\n'
    )


def test_show_version(run):
    assert run('--version').output == f'instawow, version {utils.get_version()}\n'
