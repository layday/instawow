import enum
from functools import partial
import json
from types import SimpleNamespace
from unittest.mock import patch

from click.testing import CliRunner
from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput
import pytest

from instawow.cli import main
from instawow.config import Config
from instawow.manager import CliManager, prepare_db_session
from instawow.utils import make_progress_bar


class Flavour(enum.IntEnum):
    retail = enum.auto()
    classic = enum.auto()


@pytest.fixture(scope='class', params=('retail', 'classic'))
def full_config(tmp_path_factory, request, temp_dir):
    tmp_path = tmp_path_factory.mktemp(f'{__name__}.{request.cls.__name__}')
    addons = tmp_path / 'addons'
    addons.mkdir()
    return {'config_dir': tmp_path / 'config',
            'addon_dir': addons,
            'temp_dir': temp_dir,
            'game_flavour': request.param}


@pytest.fixture(scope='class')
def manager(full_config):
    config = Config(**full_config).write()
    db_session = prepare_db_session(config=config)
    progress_bar_factory = partial(make_progress_bar, input=DummyInput(), output=DummyOutput())
    yield CliManager(config, db_session, progress_bar_factory)


@pytest.fixture(scope='class')
def run(manager, request):
    param = getattr(request, 'param', None)
    if param is Flavour.retail and manager.config.is_classic:
        pytest.skip('test is for retail only')
    elif param is Flavour.classic and not manager.config.is_classic:
        pytest.skip('test is for classic only')
    yield partial(CliRunner().invoke, main, catch_exceptions=False, obj=SimpleNamespace(m=manager))


@pytest.fixture(scope='class')
def molinari_and_run(run):
    run('install curse:molinari')
    yield run


@pytest.mark.curse
class TestValidCursePkgLifecycle:
    @pytest.mark.parametrize(
        'input, cmp',
        [('install curse:molinari',
          lambda v: v.startswith('✓ curse:molinari\n  installed')),
         ('install curse:molinari',
          '✗ curse:molinari\n  package already installed\n'.__eq__),
         ('update curse:molinari',
          '✗ curse:molinari\n  package is up to date\n'.__eq__),
         ('remove curse:molinari',
          '✓ curse:molinari\n  removed\n'.__eq__),
         ('update curse:molinari',
          '✗ curse:molinari\n  package is not installed\n'.__eq__),
         ('remove curse:molinari',
          '✗ curse:molinari\n  package is not installed\n'.__eq__),])
    def test_valid_curse_pkg_lifecycle(self, run, input, cmp):
        assert cmp(run(input).output)


@pytest.mark.tukui
class TestValidTukuiPkgLifecycle:
    @pytest.mark.parametrize(
        'input, cmp, run',
        [('install tukui:3',
          lambda v: v.startswith('✓ tukui:3\n  installed'),
          None),
         ('install tukui:3',
          '✗ tukui:3\n  package already installed\n'.__eq__,
          None),
         ('update tukui:3',
          '✗ tukui:3\n  package is up to date\n'.__eq__,
          None),
         ('remove tukui:3',
          '✓ tukui:3\n  removed\n'.__eq__,
          None),
         ('update tukui:3',
          '✗ tukui:3\n  package is not installed\n'.__eq__,
          None),
         ('remove tukui:3',
          '✗ tukui:3\n  package is not installed\n'.__eq__,
          None),
         ('install tukui:tukui',
          lambda v: v.startswith('✓ tukui:tukui\n  installed'),
          Flavour.retail),
         ('install tukui:tukui',
          '✗ tukui:tukui\n  package already installed\n'.__eq__,
          Flavour.retail),
         ('update tukui:tukui',
          '✗ tukui:tukui\n  package is up to date\n'.__eq__,
          Flavour.retail),
         ('remove tukui:tukui',
          '✓ tukui:tukui\n  removed\n'.__eq__,
          Flavour.retail),
         ('install tukui:tukui',
          '✗ tukui:tukui\n  package does not exist\n'.__eq__,
          Flavour.classic),
         ('update tukui:tukui',
          '✗ tukui:tukui\n  package is not installed\n'.__eq__,
          None),
         ('remove tukui:tukui',
          '✗ tukui:tukui\n  package is not installed\n'.__eq__,
          None),],
        indirect=('run',))
    def test_valid_tukui_pkg_lifecycle(self, run, input, cmp):
        assert cmp(run(input).output)


@pytest.mark.wowi
class TestValidWowiPkgLifecycle:
    @pytest.mark.parametrize(
        'input, cmp',
        [('install wowi:13188-molinari',
          lambda v: v.startswith('✓ wowi:13188-molinari\n  installed')),
         ('install wowi:13188-molinari',
          '✗ wowi:13188-molinari\n  package already installed\n'.__eq__),
         ('update wowi:13188-molinari',
          '✗ wowi:13188-molinari\n  package is up to date\n'.__eq__),
         ('remove wowi:13188-molinari',
          '✓ wowi:13188-molinari\n  removed\n'.__eq__),
         ('update wowi:13188-molinari',
          '✗ wowi:13188-molinari\n  package is not installed\n'.__eq__),
         ('remove wowi:13188-molinari',
          '✗ wowi:13188-molinari\n  package is not installed\n'.__eq__),])
    def test_valid_wowi_pkg_lifecycle(self, run, input, cmp):
        assert cmp(run(input).output)


class TestFolderConflictLifecycle:
    @pytest.mark.parametrize(
        'input, cmp, run',
        [('install curse:molinari',
          lambda v: v.startswith('✓ curse:molinari\n  installed'),
          Flavour.retail),
         ('install wowi:13188-molinari',
          "✗ wowi:13188-molinari\n"
          "  package folders conflict with installed package curse:molinari\n".__eq__,
          Flavour.retail),
         ('remove curse:molinari',
          '✓ curse:molinari\n  removed\n'.__eq__,
          Flavour.retail),],
        indirect=('run',))
    def test_folder_conflict_lifecycle(self, run, input, cmp):
        assert cmp(run(input).output)


class TestPreexistingFolderConflictOnInstall:
    def test_preexisting_folder_conflict_on_install(self, manager, run):
        manager.config.addon_dir.joinpath('Molinari').mkdir()
        assert (run('install curse:molinari').output
                == "✗ curse:molinari\n  package folders conflict with 'Molinari'\n")


class TestInvalidAddonNameLifecycle:
    @pytest.mark.parametrize(
        'input, output',
        [('install curse:gargantuan-wigs',
          '✗ curse:gargantuan-wigs\n  package does not exist\n'),
         ('update curse:gargantuan-wigs',
          '✗ curse:gargantuan-wigs\n  package is not installed\n'),
         ('remove curse:gargantuan-wigs',
          '✗ curse:gargantuan-wigs\n  package is not installed\n'),])
    def test_invalid_addon_name_lifecycle(self, run, input, output):
        assert run(input).output == output


class TestInvalidSourceLifecycle:
    @pytest.mark.parametrize(
        'input, output',
        [('install foo:bar',
          '✗ foo:bar\n  package source is invalid\n'),
         ('update foo:bar',
          '✗ foo:bar\n  package is not installed\n'),
         ('remove foo:bar',
          '✗ foo:bar\n  package is not installed\n'),])
    def test_invalid_source_lifecycle(self, run, input, output):
        assert run(input).output == output


class TestInstallWithAlias:
    @pytest.mark.curse
    @pytest.mark.parametrize(
        'input, cmp',
        [('install curse:molinari',
          lambda v: v.startswith('✓ curse:molinari\n  installed')),
         ('install curse:20338',
          '✗ curse:20338\n  package already installed\n'.__eq__),
         ('install https://www.wowace.com/projects/molinari',
          '✗ curse:molinari\n  package already installed\n'.__eq__),
         ('install https://www.curseforge.com/wow/addons/molinari',
          '✗ curse:molinari\n  package already installed\n'.__eq__),
         ('install https://www.curseforge.com/wow/addons/molinari/download',
          '✗ curse:molinari\n  package already installed\n'.__eq__),
         ('remove curse:molinari',
          '✓ curse:molinari\n  removed\n'.__eq__),])
    def test_install_with_curse_alias(self, run, input, cmp):
        assert cmp(run(input).output)

    @pytest.mark.tukui
    @pytest.mark.parametrize(
        'input, cmp, run',
        [('install tukui:-1',
          lambda v: v.startswith('✓ tukui:-1\n  installed'),
          Flavour.retail),
         ('install tukui:-1',
          '✗ tukui:-1\n  package does not exist\n'.__eq__,
          Flavour.classic),
         ('install tukui:tukui',
          '✗ tukui:tukui\n  package already installed\n'.__eq__,
          Flavour.retail),
         ('install tukui:tukui',
          '✗ tukui:tukui\n  package does not exist\n'.__eq__,
          Flavour.classic),
         ('install https://www.tukui.org/download.php?ui=tukui',
          '✗ tukui:tukui\n  package already installed\n'.__eq__,
          Flavour.retail),
         ('install https://www.tukui.org/download.php?ui=tukui',
          '✗ tukui:tukui\n  package does not exist\n'.__eq__,
          Flavour.classic),
         ('install https://www.tukui.org/addons.php?id=3',
          lambda v: v.startswith('✓ tukui:3\n  installed'),
          None),
         ('install tukui:3',
          '✗ tukui:3\n  package already installed\n'.__eq__,
          None),
         ('remove tukui:3',
          '✓ tukui:3\n  removed\n'.__eq__,
          None),],
        indirect=('run',))
    def test_install_with_tukui_alias(self, run, input, cmp):
        assert cmp(run(input).output)

    @pytest.mark.wowi
    @pytest.mark.parametrize(
        'input, cmp',
        [('install wowi:21654',
          lambda v: v.startswith('✓ wowi:21654\n  installed')),
         ('install wowi:21654-dejamark',
          '✗ wowi:21654-dejamark\n  package already installed\n'.__eq__),
         ('install https://www.wowinterface.com/downloads/landing.php?fileid=21654',
          '✗ wowi:21654\n  package already installed\n'.__eq__),
         ('install https://www.wowinterface.com/downloads/fileinfo.php?id=21654',
          '✗ wowi:21654\n  package already installed\n'.__eq__),
         ('install https://www.wowinterface.com/downloads/download21654-DejaMark',
          '✗ wowi:21654\n  package already installed\n'.__eq__),
         ('remove wowi:21654',
          '✓ wowi:21654\n  removed\n'.__eq__),])
    def test_install_with_wowi_alias(self, run, input, cmp):
        assert cmp(run(input).output)


class TestMissingDirOnRemove:
    def test_missing_dir_on_remove(self, manager, molinari_and_run):
        addon_dir = manager.config.addon_dir
        addon_dir.joinpath('Molinari').rename(addon_dir.joinpath('NotMolinari'))
        assert molinari_and_run('remove curse:molinari').output == '✓ curse:molinari\n  removed\n'


class TestNonDestructiveOps:
    @pytest.mark.parametrize(
        'command, exit_code',
        [('list mol', 0), ('info foo', 0),
         ('visit mol', 0), ('visit foo', 1),
         ('reveal mol', 0), ('reveal foo', 1),])
    @patch('webbrowser.open', lambda v: ...)
    def test_exit_codes_with_substr_match(self, molinari_and_run, command, exit_code):
        assert molinari_and_run(command).exit_code == exit_code

    def test_substr_list_match(self, molinari_and_run):
        assert molinari_and_run('list mol').output == 'curse:molinari\n'
        assert molinari_and_run('list foo').output == ''
        assert molinari_and_run('list -f detailed mol').output.startswith('curse:molinari')
        molinari, = json.loads(molinari_and_run('list -f json mol').output)
        assert (molinari['source'], molinari['slug']) == ('curse', 'molinari')


class TestCsvExportImport:
    @pytest.fixture(autouse=True, scope='class')
    def export(self, tmp_path_factory, molinari_and_run):
        export_csv = tmp_path_factory.mktemp('export', numbered=True).joinpath('export.csv')
        molinari_and_run(f'list -e {export_csv}')
        yield export_csv

    def test_export_to_csv(self, export):
        assert export.read_text(encoding='utf-8') == '''\
defn,strategy
curse:molinari,default
'''

    def test_import_from_csv(self, molinari_and_run, export):
        assert molinari_and_run(f'install -i {export}').output == '''\
✗ curse:molinari
  package already installed
'''
