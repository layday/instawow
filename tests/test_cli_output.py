
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
        addons = tmp_path/'addons'
        addons.mkdir()
        config = Config(config_dir=tmp_path/'config', addon_dir=addons)
        config.write()
        yield CliManager(config=config, show_progress=False)

    @pytest.fixture(scope='class')
    def invoke_runner(self, manager):
        yield lambda args: CliRunner().invoke(main, args=args, obj=manager)


class TestValidCursePkgLifecycle(_CliTest):

    @pytest.mark.parametrize(
        'test_input, cmp_fn, expected_output',
        [(['install', 'curse:molinari'],
          str.startswith,
          '✓ curse:molinari: installed'),
         (['install', 'curse:molinari'],
          str.__eq__,
          '✗ curse:molinari: already installed\n'),
         (['update', 'curse:molinari'],
          str.__eq__,
          '✗ curse:molinari: no update available\n'),
         (['remove', 'curse:molinari'],
          str.__eq__,
          '✓ curse:molinari: removed\n'),
         (['update', 'curse:molinari'],
          str.__eq__,
          '✗ curse:molinari: not installed\n'),
         (['remove', 'curse:molinari'],
          str.__eq__,
          '✗ curse:molinari: not installed\n'),])
    def test_valid_curse_pkg_lifecycle(self, invoke_runner,
                                       test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestValidTukuiPkgLifecycle(_CliTest):

    @pytest.mark.parametrize(
        'test_input, cmp_fn, expected_output',
        [(['install', 'tukui:3'],
          str.startswith,
          '✓ tukui:3: installed'),
         (['install', 'tukui:3'],
          str.__eq__,
          '✗ tukui:3: already installed\n'),
         (['update', 'tukui:3'],
          str.__eq__,
          '✗ tukui:3: no update available\n'),
         (['remove', 'tukui:3'],
          str.__eq__,
          '✓ tukui:3: removed\n'),
         (['update', 'tukui:3'],
          str.__eq__,
          '✗ tukui:3: not installed\n'),
         (['remove', 'tukui:3'],
          str.__eq__,
          '✗ tukui:3: not installed\n'),
         (['install', 'tukui:tukui'],
          str.startswith,
          '✓ tukui:tukui: installed'),
         (['install', 'tukui:tukui'],
          str.__eq__,
          '✗ tukui:tukui: already installed\n'),
         (['update', 'tukui:tukui'],
          str.__eq__,
          '✗ tukui:tukui: no update available\n'),
         (['remove', 'tukui:tukui'],
          str.__eq__,
          '✓ tukui:tukui: removed\n'),
         (['update', 'tukui:tukui'],
          str.__eq__,
          '✗ tukui:tukui: not installed\n'),
         (['remove', 'tukui:tukui'],
          str.__eq__,
          '✗ tukui:tukui: not installed\n'),])
    def test_valid_tukui_pkg_lifecycle(self, invoke_runner,
                                       test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestValidWowiPkgLifecycle(_CliTest):

    @pytest.mark.parametrize(
        'test_input, cmp_fn, expected_output',
        [(['install', 'wowi:13188-molinari'],
          str.startswith,
          '✓ wowi:13188-molinari: installed'),
         (['install', 'wowi:13188-molinari'],
          str.__eq__,
          '✗ wowi:13188-molinari: already installed\n'),
         (['update', 'wowi:13188-molinari'],
          str.__eq__,
          '✗ wowi:13188-molinari: no update available\n'),
         (['remove', 'wowi:13188-molinari'],
          str.__eq__,
          '✓ wowi:13188-molinari: removed\n'),
         (['update', 'wowi:13188-molinari'],
          str.__eq__,
          '✗ wowi:13188-molinari: not installed\n'),
         (['remove', 'wowi:13188-molinari'],
          str.__eq__,
          '✗ wowi:13188-molinari: not installed\n'),])
    def test_valid_wowi_pkg_lifecycle(self, invoke_runner,
                                      test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestFolderConflictLifecycle(_CliTest):

    @pytest.mark.parametrize('test_input, cmp_fn, expected_output',
                             [(['install', 'curse:molinari'],
                               str.startswith,
                               '✓ curse:molinari: installed'),
                              (['install', 'wowi:13188-molinari'],
                               str.__eq__,
                               '✗ wowi:13188-molinari: conflicts with installed add-on '
                               'curse:molinari\n'),
                              (['remove', 'curse:molinari'],
                               str.__eq__,
                               '✓ curse:molinari: removed\n'),])
    def test_folder_conflict_lifecycle(self, invoke_runner,
                                       test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestPreexistingFolderConflictOnInstall(_CliTest):

    def test_preexisting_folder_conflict_on_install(self, invoke_runner, manager):
        (manager.config.addon_dir/'Molinari').mkdir()
        assert invoke_runner(['install', 'curse:molinari']).output == \
            '✗ curse:molinari: conflicts with an add-on not installed by instawow\n'\
            '  pass `-o` to `install` if you do actually wish to overwrite this add-on\n'


class TestInvalidAddonNameLifecycle(_CliTest):

    @pytest.mark.parametrize('test_input, expected_output',
                             [(['install', 'curse:gargantuan-wigs'],
                               '✗ curse:gargantuan-wigs: no such project id or slug\n'),
                              (['update', 'curse:gargantuan-wigs'],
                               '✗ curse:gargantuan-wigs: not installed\n'),
                              (['remove', 'curse:gargantuan-wigs'],
                               '✗ curse:gargantuan-wigs: not installed\n')])
    def test_invalid_addon_name_lifecycle(self, invoke_runner,
                                          test_input, expected_output):
        assert invoke_runner(test_input).output == expected_output


class TestInvalidOriginLifecycle(_CliTest):

    @pytest.mark.parametrize('test_input, expected_output',
                             [(['install', 'foo:bar'],
                               '✗ foo:bar: invalid origin\n'),
                              (['update', 'foo:bar'],
                               '✗ foo:bar: not installed\n'),
                              (['remove', 'foo:bar'],
                               '✗ foo:bar: not installed\n')])
    def test_invalid_origin_lifecycle(self, invoke_runner,
                                      test_input, expected_output):
        assert invoke_runner(test_input).output == expected_output


class TestStrategySwitchAndUpdateLifecycle(_CliTest):

    @pytest.mark.parametrize('test_input, cmp_fn, expected_output',
                             [(['install', 'curse:kuinameplates'],
                               str.startswith,
                               '✓ curse:kuinameplates: installed'),
                              (['update', '--strategy=latest', 'curse:kuinameplates'],
                               str.startswith,
                               '✓ curse:kuinameplates: updated'),
                              (['update', '--strategy=canonical'],
                               str.startswith,
                               '✓ curse:kuinameplates: updated'),
                              (['remove', 'curse:kuinameplates'],
                               str.__eq__,
                               '✓ curse:kuinameplates: removed\n'),])
    def test_strategy_switch_and_update_lifecycle(self, invoke_runner,
                                                  test_input, cmp_fn,
                                                  expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestInstallWithAlias(_CliTest):

    @pytest.mark.parametrize(
        'test_input, cmp_fn, expected_output',
        [(['install', 'curse:molinari'],
          str.startswith,
          '✓ curse:molinari: installed'),
         (['install', 'curse:20338'],
          str.__eq__,
          '✗ curse:20338: already installed\n'),
         (['install', 'https://wow.curseforge.com/projects/molinari'],
          str.__eq__,
          '✗ curse:molinari: already installed\n'),
         (['install', 'https://www.curseforge.com/wow/addons/molinari'],
          str.__eq__,
          '✗ curse:molinari: already installed\n'),
         (['install', 'https://www.curseforge.com/wow/addons/molinari/download'],
          str.__eq__,
          '✗ curse:molinari: already installed\n'),
         (['remove', 'curse:molinari'],
          str.__eq__,
          '✓ curse:molinari: removed\n'),])
    def test_install_with_curse_alias(self, invoke_runner,
                                      test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)

    def test_install_with_tukui_addon_alias(self, invoke_runner):
        assert invoke_runner(['install', 'https://www.tukui.org/addons.php?id=3'])\
            .output\
            .startswith('✓ tukui:3: installed')

    def test_install_with_tukui_ui_alias(self, invoke_runner):
        assert invoke_runner(['install', 'https://www.tukui.org/download.php?ui=tukui'])\
            .output\
            .startswith('✓ tukui:tukui: installed')

    @pytest.mark.parametrize(
        'test_input, cmp_fn, expected_output',
        [(['install', 'wowi:10783'],
          str.startswith,
          '✓ wowi:10783: installed'),
         (['install', 'https://www.wowinterface.com/downloads/info10783-Prat3.0.html'],
          str.__eq__,
          '✗ wowi:10783: already installed\n'),
         (['install', 'https://www.wowinterface.com/downloads/download10783-Prat3'],
          str.__eq__,
          '✗ wowi:10783: already installed\n'),
         (['remove', 'wowi:10783'],
          str.__eq__,
          '✓ wowi:10783: removed\n'),])
    def test_install_with_wowi_alias(self, invoke_runner,
                                     test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)
