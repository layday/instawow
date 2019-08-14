
from click.testing import CliRunner
import pytest

from instawow.cli import main
from instawow.config import Config
from instawow.manager import CliManager


class _CliTest:

    @pytest.fixture(scope='class')
    def manager(self, tmp_path_factory, request):
        tmp_path = tmp_path_factory.mktemp('.'.join((__name__,
                                                     request.cls.__name__)))
        addons = tmp_path / 'addons'
        addons.mkdir()
        config = Config(config_dir=tmp_path / 'config', addon_dir=addons)
        config.write()
        yield CliManager(config, show_progress=False)

    @pytest.fixture(scope='class')
    def invoke_runner(self, manager):
        yield lambda args: CliRunner().invoke(main, args=args, obj=manager)


class TestValidCursePkgLifecycle(_CliTest):

    @pytest.mark.parametrize(
        'test_input, cmp_fn, expected_output',
        [('install curse:molinari',
          str.startswith,
          '✓ curse:molinari\n  installed'),
         ('install curse:molinari',
          str.__eq__,
          '✗ curse:molinari\n  package already installed\n'),
         ('update curse:molinari',
          str.__eq__,
          '✗ curse:molinari\n  package is up to date\n'),
         ('remove curse:molinari',
          str.__eq__,
          '✓ curse:molinari\n  removed\n'),
         ('update curse:molinari',
          str.__eq__,
          '✗ curse:molinari\n  package is not installed\n'),
         ('remove curse:molinari',
          str.__eq__,
          '✗ curse:molinari\n  package is not installed\n'),])
    def test_valid_curse_pkg_lifecycle(self, invoke_runner,
                                       test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestValidClassicCursePkgLifecycle(_CliTest):

    @pytest.mark.parametrize(
        'test_input, cmp_fn, expected_output',
        [('install curse+classic:details',
          str.startswith,
          '✓ curse+classic:details\n  installed'),
         ('install curse+classic:details',
          str.__eq__,
          '✗ curse+classic:details\n  package already installed\n'),
         ('update curse+classic:details',
          str.__eq__,
          '✗ curse+classic:details\n  package is up to date\n'),
         ('remove curse+classic:details',
          str.__eq__,
          '✓ curse+classic:details\n  removed\n'),
         ('update curse+classic:details',
          str.__eq__,
          '✗ curse+classic:details\n  package is not installed\n'),
         ('remove curse+classic:details',
          str.__eq__,
          '✗ curse+classic:details\n  package is not installed\n'),])
    def test_valid_curse_pkg_lifecycle(self, invoke_runner,
                                       test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestValidTukuiPkgLifecycle(_CliTest):

    @pytest.mark.parametrize(
        'test_input, cmp_fn, expected_output',
        [('install tukui:3',
          str.startswith,
          '✓ tukui:3\n  installed'),
         ('install tukui:3',
          str.__eq__,
          '✗ tukui:3\n  package already installed\n'),
         ('update tukui:3',
          str.__eq__,
          '✗ tukui:3\n  package is up to date\n'),
         ('remove tukui:3',
          str.__eq__,
          '✓ tukui:3\n  removed\n'),
         ('update tukui:3',
          str.__eq__,
          '✗ tukui:3\n  package is not installed\n'),
         ('remove tukui:3',
          str.__eq__,
          '✗ tukui:3\n  package is not installed\n'),
         ('install tukui:tukui',
          str.startswith,
          '✓ tukui:tukui\n  installed'),
         ('install tukui:tukui',
          str.__eq__,
          '✗ tukui:tukui\n  package already installed\n'),
         ('update tukui:tukui',
          str.__eq__,
          '✗ tukui:tukui\n  package is up to date\n'),
         ('remove tukui:tukui',
          str.__eq__,
          '✓ tukui:tukui\n  removed\n'),
         ('update tukui:tukui',
          str.__eq__,
          '✗ tukui:tukui\n  package is not installed\n'),
         ('remove tukui:tukui',
          str.__eq__,
          '✗ tukui:tukui\n  package is not installed\n'),
        ])
    # @pytest.mark.skip(reason='corrupted zip files')
    def test_valid_tukui_pkg_lifecycle(self, invoke_runner,
                                       test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestValidWowiPkgLifecycle(_CliTest):

    @pytest.mark.parametrize(
        'test_input, cmp_fn, expected_output',
        [('install wowi:13188-molinari',
          str.startswith,
          '✓ wowi:13188-molinari\n  installed'),
         ('install wowi:13188-molinari',
          str.__eq__,
          '✗ wowi:13188-molinari\n  package already installed\n'),
         ('update wowi:13188-molinari',
          str.__eq__,
          '✗ wowi:13188-molinari\n  package is up to date\n'),
         ('remove wowi:13188-molinari',
          str.__eq__,
          '✓ wowi:13188-molinari\n  removed\n'),
         ('update wowi:13188-molinari',
          str.__eq__,
          '✗ wowi:13188-molinari\n  package is not installed\n'),
         ('remove wowi:13188-molinari',
          str.__eq__,
          '✗ wowi:13188-molinari\n  package is not installed\n'),
        ])
    def test_valid_wowi_pkg_lifecycle(self, invoke_runner,
                                      test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestFolderConflictLifecycle(_CliTest):

    @pytest.mark.parametrize('test_input, cmp_fn, expected_output',
                             [('install curse:molinari',
                               str.startswith,
                               '✓ curse:molinari\n  installed'),
                              ('install wowi:13188-molinari',
                               str.__eq__,
                               "✗ wowi:13188-molinari\n"
                               "  package folders conflict with installed package's curse:molinari\n"),
                              ('remove curse:molinari',
                               str.__eq__,
                               '✓ curse:molinari\n  removed\n'),
                             ])
    def test_folder_conflict_lifecycle(self, invoke_runner,
                                       test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestPreexistingFolderConflictOnInstall(_CliTest):

    def test_preexisting_folder_conflict_on_install(self, manager, invoke_runner):
        (manager.config.addon_dir / 'Molinari').mkdir()
        assert invoke_runner('install curse:molinari').output == \
            "✗ curse:molinari\n  package folders conflict with an add-on's not controlled by instawow\n"


class TestInvalidAddonNameLifecycle(_CliTest):

    @pytest.mark.parametrize('test_input, expected_output',
                             [('install curse:gargantuan-wigs',
                               '✗ curse:gargantuan-wigs\n  package does not exist\n'),
                              ('update curse:gargantuan-wigs',
                               '✗ curse:gargantuan-wigs\n  package is not installed\n'),
                              ('remove curse:gargantuan-wigs',
                               '✗ curse:gargantuan-wigs\n  package is not installed\n')
                             ])
    def test_invalid_addon_name_lifecycle(self, invoke_runner,
                                          test_input, expected_output):
        assert invoke_runner(test_input).output == expected_output


class TestInvalidOriginLifecycle(_CliTest):

    @pytest.mark.parametrize('test_input, expected_output',
                             [('install foo:bar',
                               '✗ foo:bar\n  package origin is invalid\n'),
                              ('update foo:bar',
                               '✗ foo:bar\n  package is not installed\n'),
                              ('remove foo:bar',
                               '✗ foo:bar\n  package is not installed\n')
                             ])
    def test_invalid_origin_lifecycle(self, invoke_runner,
                                      test_input, expected_output):
        assert invoke_runner(test_input).output == expected_output


class TestStrategySwitchAndUpdateLifecycle(_CliTest):

    @pytest.mark.parametrize('test_input, cmp_fn, expected_output',
                             [('install curse:kuinameplates',
                               str.startswith,
                               '✓ curse:kuinameplates\n  installed'),
                              ('update --strategy=latest curse:kuinameplates',
                               str.startswith,
                               '✓ curse:kuinameplates\n  updated'),
                              ('update --strategy=default curse:kuinameplates',
                               str.startswith,
                               '✓ curse:kuinameplates\n  updated'),
                              ('remove curse:kuinameplates',
                               str.__eq__,
                               '✓ curse:kuinameplates\n  removed\n'),
                             ])
    def test_strategy_switch_and_update_lifecycle(self, invoke_runner,
                                                  test_input, cmp_fn,
                                                  expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestInstallWithAlias(_CliTest):

    @pytest.mark.parametrize(
        'test_input, cmp_fn, expected_output',
        [('install curse:molinari',
          str.startswith,
          '✓ curse:molinari\n  installed'),
         ('install curse:20338',
          str.__eq__,
          '✗ curse:20338\n  package already installed\n'),
         ('install https://www.wowace.com/projects/molinari',
          str.__eq__,
          '✗ curse:molinari\n  package already installed\n'),
         ('install https://www.curseforge.com/wow/addons/molinari',
          str.__eq__,
          '✗ curse:molinari\n  package already installed\n'),
         ('install https://www.curseforge.com/wow/addons/molinari/download',
          str.__eq__,
          '✗ curse:molinari\n  package already installed\n'),
         ('remove curse:molinari',
          str.__eq__,
          '✓ curse:molinari\n  removed\n'),
        ])
    def test_install_with_curse_alias(self, invoke_runner,
                                      test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)

    # @pytest.mark.skip(reason='corrupted zip files')
    def test_install_with_tukui_addon_alias(self, invoke_runner):
        assert invoke_runner('install https://www.tukui.org/addons.php?id=3')\
            .output\
            .startswith('✓ tukui:3\n  installed')


    # @pytest.mark.skip(reason='corrupted zip files')
    def test_install_with_tukui_ui_alias(self, invoke_runner):
        assert invoke_runner('install https://www.tukui.org/download.php?ui=tukui')\
            .output\
            .startswith('✓ tukui:tukui\n  installed')

    @pytest.mark.parametrize(
        'test_input, cmp_fn, expected_output',
        [('install wowi:10783',
          str.startswith,
          '✓ wowi:10783\n  installed'),
         ('install https://www.wowinterface.com/downloads/info10783-Prat3.0.html',
          str.__eq__,
          '✗ wowi:10783\n  package already installed\n'),
         ('install https://www.wowinterface.com/downloads/landing.php?fileid=10783',
          str.__eq__,
          '✗ wowi:10783\n  package already installed\n'),
         ('remove wowi:10783',
          str.__eq__,
          '✓ wowi:10783\n  removed\n'),
        ])
    def test_install_with_wowi_alias(self, invoke_runner,
                                     test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)
