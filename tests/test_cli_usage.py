
from click.testing import CliRunner
import pytest

from instawow.cli import main
from instawow.config import Config
from instawow.manager import Manager


class _CliTest:

    @pytest.fixture(autouse=True,
                    scope='class')
    def temp_dirs(self, tmpdir_factory, request):
        factory = tmpdir_factory.mktemp('.'.join((__name__, request.cls.__name__)))
        self.addons = factory.mkdir('addons')
        self.config = factory.mkdir('config')
        return factory

    @pytest.fixture(scope='class')
    def invoke_runner(self, temp_dirs):
        with Manager(config=Config(addon_dir=self.addons, config_dir=self.config),
                     show_progress=False) as manager:
            yield lambda args: CliRunner().invoke(main, args=args, obj=manager)


class TestSingleValidCursePkgLifecycle(_CliTest):

    @pytest.mark.parametrize('test_input, cmp_fn, expected_output',
                             [(['install', 'curse:molinari'],
                               str.startswith,
                               '✓ curse:molinari: installed'),
                              (['install', 'curse:molinari'],
                               str.__eq__,
                               '✗ curse:molinari: already installed\n'),
                              (['update', 'curse:molinari'],
                               str.__eq__,
                               ''),
                              (['set', '--strategy=latest', 'curse:molinari'],
                               str.__eq__,
                               "✓ curse:molinari: strategy set to latest\n"),
                              (['remove', 'curse:molinari'],
                               str.__eq__,
                               '✓ curse:molinari: removed\n'),
                              (['update', 'curse:molinari'],
                               str.__eq__,
                               '✗ curse:molinari: not installed\n'),
                              (['set', '--strategy=latest', 'curse:molinari'],
                               str.__eq__,
                               '✗ curse:molinari: not installed\n'),
                              (['remove', 'curse:molinari'],
                               str.__eq__,
                               '✗ curse:molinari: not installed\n'),])
    def test_single_valid_curse_pkg_lifecycle(self, invoke_runner,
                                              test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestSingleValidWowiPkgLifecycle(_CliTest):

    @pytest.mark.parametrize('test_input, cmp_fn, expected_output',
                             [(['install', 'wowi:13188-Molinari'],
                               str.startswith,
                               '✓ wowi:13188-Molinari: installed'),
                              (['install', 'wowi:13188-Molinari'],
                               str.__eq__,
                               '✗ wowi:13188-Molinari: already installed\n'),
                              (['update', 'wowi:13188-Molinari'],
                               str.__eq__,
                               ''),
                              (['remove', 'wowi:13188-Molinari'],
                               str.__eq__,
                               '✓ wowi:13188-Molinari: removed\n'),
                              (['update', 'wowi:13188-Molinari'],
                               str.__eq__,
                               '✗ wowi:13188-Molinari: not installed\n'),
                              (['remove', 'wowi:13188-Molinari'],
                               str.__eq__,
                               '✗ wowi:13188-Molinari: not installed\n'),])
    def test_single_valid_wowi_pkg_lifecycle(self, invoke_runner,
                                             test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestFolderConflictLifecycle(_CliTest):

    @pytest.mark.parametrize('test_input, cmp_fn, expected_output',
                             [(['install', 'curse:molinari'],
                               str.startswith,
                               '✓ curse:molinari: installed'),
                              (['install', 'wowi:13188-Molinari'],
                               str.__eq__,
                               '✗ wowi:13188-Molinari: conflicts with installed add-on '
                               'curse:molinari\n'),
                              (['remove', 'curse:molinari'],
                               str.__eq__,
                               '✓ curse:molinari: removed\n'),])
    def test_folder_conflict_lifecycle(self, invoke_runner,
                                       test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestPreexistingFolderConflictOnInstall(_CliTest):

    def test_preexisting_folder_conflict_on_install(self, invoke_runner,
                                                    temp_dirs):
        temp_dirs.mkdir('addons', 'Molinari')
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
                             [(['install', 'curse:transcriptor'],
                               str.startswith,
                               '✓ curse:transcriptor: installed'),
                              (['set', '--strategy=latest', 'curse:transcriptor'],
                               str.__eq__,
                               "✓ curse:transcriptor: strategy set to latest\n"),
                              (['update', 'curse:transcriptor'],
                               str.startswith,
                               '✓ curse:transcriptor: updated from'),
                              (['set', '--strategy=canonical', 'curse:transcriptor'],
                               str.__eq__,
                               "✓ curse:transcriptor: strategy set to canonical\n"),
                              (['update'],
                               str.startswith,
                               '✓ curse:transcriptor: updated from'),
                              (['remove', 'curse:transcriptor'],
                               str.__eq__,
                               '✓ curse:transcriptor: removed\n'),])
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
         (['install', 'https://mods.curse.com/project/20338'],
          str.__eq__,
          '✗ curse:20338: already installed\n'),
         (['install', 'https://mods.curse.com/addons/wow/molinari'],
          str.__eq__,
          '✗ curse:molinari: already installed\n'),
         (['install', 'https://mods.curse.com/addons/wow/molinari/download'],
          str.__eq__,
          '✗ curse:molinari: already installed\n'),
         (['remove', 'curse:molinari'],
          str.__eq__,
          '✓ curse:molinari: removed\n'),])
    def test_install_with_curse_alias(self, invoke_runner,
                                      test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)

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
