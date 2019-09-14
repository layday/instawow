
from enum import IntEnum, auto
from functools import partial
from unittest.mock import patch

from click.testing import CliRunner
from prompt_toolkit.input import DummyInput
from prompt_toolkit.output import DummyOutput
import pytest

from instawow.cli import main
from instawow.config import Config
from instawow.manager import CliManager
from instawow.utils import make_progress_bar


class Flavour(IntEnum):
    retail = auto()
    classic = auto()


@pytest.fixture(scope='class', params=('retail', 'classic'))
def full_config(tmp_path_factory, request):
    path = tmp_path_factory.mktemp(f'{__name__}.{request.cls.__name__}')
    config = path / 'config'
    addons = path / 'addons'
    addons.mkdir()
    return {'config_dir': config, 'addon_dir': addons, 'game_flavour': request.param}


@pytest.fixture(scope='class')
def obj(full_config):
    config = Config(**full_config).write()
    progress_bar_factory = lambda: make_progress_bar(input=DummyInput(), output=DummyOutput())
    manager = CliManager(config, progress_bar_factory)
    yield type('Manager', (), {'manager': manager, 'm': manager})


@pytest.fixture(scope='class')
def run(obj, request):
    param = getattr(request, 'param', None)
    if param is Flavour.retail and obj.m.config.is_classic:
        pytest.skip('test is for retail only')
    elif param is Flavour.classic and not obj.m.config.is_classic:
        pytest.skip('test is for classic only')
    yield partial(CliRunner().invoke, main, obj=obj)


@pytest.fixture(scope='class')
def run_moli_run(run):
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
          '✗ curse:molinari\n  package is not installed\n'.__eq__),],)
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
        'input, cmp, run',
        [('install wowi:13188-molinari',
          lambda v: v.startswith('✓ wowi:13188-molinari\n  installed'),
          Flavour.retail),
         ('install wowi:13188-molinari',
          '✗ wowi:13188-molinari\n  package already installed\n'.__eq__,
          Flavour.retail),
         ('update wowi:13188-molinari',
          '✗ wowi:13188-molinari\n  package is up to date\n'.__eq__,
          Flavour.retail),
         ('remove wowi:13188-molinari',
          '✓ wowi:13188-molinari\n  removed\n'.__eq__,
          Flavour.retail),
         ('update wowi:13188-molinari',
          '✗ wowi:13188-molinari\n  package is not installed\n'.__eq__,
          Flavour.retail),
         ('remove wowi:13188-molinari',
          '✗ wowi:13188-molinari\n  package is not installed\n'.__eq__,
          Flavour.retail),],
        indirect=('run',))
    def test_valid_wowi_pkg_lifecycle(self, run, input, cmp):
        assert cmp(run(input).output)

    @pytest.mark.parametrize(
        'input, cmp, run',
        [('install wowi:21654-dejamark',
           lambda v: v.startswith('✓ wowi:21654-dejamark\n  installed'),
          None),
         ('install wowi:13188-molinari',
          lambda v: v.startswith('✓ wowi:13188-molinari\n  installed'),
          Flavour.retail),
         ('install wowi:13188-molinari',
          '✗ wowi:13188-molinari\n  file is not compatible with classic\n'.__eq__,
          Flavour.classic),
         ('install wowi:24972-ravenclassic',
          '✗ wowi:24972-ravenclassic\n  file is only compatible with classic\n'.__eq__,
          Flavour.retail),
         ('install wowi:24972-ravenclassic',
         lambda v: v.startswith('✓ wowi:24972-ravenclassic\n  installed'),
          Flavour.classic),],
        indirect=('run',))
    def test_install_flavoursome_wowi_pkg(self, run, input, cmp):
        assert cmp(run(input).output)


class TestFolderConflictLifecycle:

    @pytest.mark.parametrize('input, cmp, run',
                             [('install curse:molinari',
                               lambda v: v.startswith('✓ curse:molinari\n  installed'),
                               Flavour.retail),
                              ('install wowi:13188-molinari',
                               "✗ wowi:13188-molinari\n"
                               "  package folders conflict with installed package's curse:molinari\n".__eq__,
                               Flavour.retail),
                              ('remove curse:molinari',
                               '✓ curse:molinari\n  removed\n'.__eq__,
                               Flavour.retail),],
                             indirect=('run',))
    def test_folder_conflict_lifecycle(self, run, input, cmp):
        assert cmp(run(input).output)


class TestPreexistingFolderConflictOnInstall:

    def test_preexisting_folder_conflict_on_install(self, obj, run):
        (obj.m.config.addon_dir / 'Molinari').mkdir()
        assert (run('install curse:molinari').output
                == "✗ curse:molinari\n  package folders conflict with an add-on's "
                   "not controlled by instawow\n")


class TestInvalidAddonNameLifecycle:

    @pytest.mark.parametrize('input, output',
                             [('install curse:gargantuan-wigs',
                               '✗ curse:gargantuan-wigs\n  package does not exist\n'),
                              ('update curse:gargantuan-wigs',
                               '✗ curse:gargantuan-wigs\n  package is not installed\n'),
                              ('remove curse:gargantuan-wigs',
                               '✗ curse:gargantuan-wigs\n  package is not installed\n'),])
    def test_invalid_addon_name_lifecycle(self, run, input, output):
        assert run(input).output == output


class TestInvalidOriginLifecycle:

    @pytest.mark.parametrize('input, output',
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
    def test_install_with_tukui_addon_alias(self, run):
        assert (run('install https://www.tukui.org/addons.php?id=3')
                .output
                .startswith('✓ tukui:3\n  installed'))

    @pytest.mark.tukui
    @pytest.mark.parametrize(
        'message, run',
        [('✓ tukui:tukui\n  installed',
          Flavour.retail),
         ('✗ tukui:tukui\n  package does not exist',
          Flavour.classic)],
        indirect=('run',))
    def test_install_with_tukui_ui_alias(self, run, message):
        assert (run('install https://www.tukui.org/download.php?ui=tukui')
                .output
                .startswith(message))

    @pytest.mark.wowi
    @pytest.mark.parametrize(
        'input, cmp',
        [('install wowi:21654',
          lambda v: v.startswith('✓ wowi:21654\n  installed')),
         ('install https://www.wowinterface.com/downloads/info21654-DejaMark.html',
          '✗ wowi:21654\n  package already installed\n'.__eq__),
         ('install https://www.wowinterface.com/downloads/landing.php?fileid=21654',
          '✗ wowi:21654\n  package already installed\n'.__eq__),
         ('install https://www.wowinterface.com/downloads/download21654-DejaMark',
          '✗ wowi:21654\n  package already installed\n'.__eq__),
         ('remove wowi:21654',
          '✓ wowi:21654\n  removed\n'.__eq__)],)
    def test_install_with_wowi_alias(self, run, input, cmp):
        assert cmp(run(input).output)


class TestNonDestructiveOps:

    @pytest.mark.parametrize('command, exit_code',
                             [('info mol', 0), ('info foo', 1),
                              ('visit mol', 0), ('visit foo', 1),
                              ('reveal mol', 0), ('reveal foo', 1),])
    @patch('webbrowser.open', lambda v: ...)
    def test_substr_op_exit_codes(self, run_moli_run, command, exit_code):
        assert run_moli_run(command).exit_code == exit_code
