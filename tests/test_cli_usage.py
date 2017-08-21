
import re

from click.testing import CliRunner
import pytest

from instawow.cli import main
from instawow.config import Config
from instawow.manager import Manager


@pytest.fixture(autouse=True,
                scope='class')
def mktmpdir(tmpdir_factory, request):
    factory = tmpdir_factory.mktemp('.'.join((__name__, request.cls.__name__)))
    factory.mkdir('addons')
    factory.mkdir('config')
    return factory


@pytest.fixture(scope='class')
def invoke_runner(mktmpdir):
    manager = Manager(config=Config(
        addon_dir=mktmpdir.join('addons'),config_dir=mktmpdir.join('config')))
    yield lambda args: CliRunner().invoke(main, args=args, obj=manager)
    manager.close()


class TestSingleValidCursePkgLifecycle:

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
                               "✓ curse:molinari: 'strategy' set to 'latest'\n"),
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


class TestSingleValidWowiPkgLifecycle:

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


class TestFolderConflictLifecycle:

    @pytest.mark.parametrize('test_input, cmp_fn, expected_output',
                             [(['install', 'curse:molinari'],
                               str.startswith,
                               '✓ curse:molinari: installed'),
                              (['install', 'wowi:13188-Molinari'],
                               str.__eq__,
                               '✗ wowi:13188-Molinari: conflicts with '
                               'curse:molinari\n'),
                              (['remove', 'curse:molinari'],
                               str.__eq__,
                               '✓ curse:molinari: removed\n'),])
    def test_folder_conflict_lifecycle(self, invoke_runner,
                                       test_input, cmp_fn, expected_output):
        assert cmp_fn(invoke_runner(test_input).output, expected_output)


class TestPreexistingFolderConflictOnInstall:

    def test_preexisting_folder_conflict_on_install(self, invoke_runner,
                                                    mktmpdir):
        mktmpdir.mkdir('addons', 'Molinari')
        assert invoke_runner(['install', 'curse:molinari']).output == \
            '✗ curse:molinari: conflicts with an add-on not installed by instawow\n'\
            'pass `-o` to `install` if you do actually wish to overwrite this add-on\n'


class TestInvalidAddonNameLifecycle:

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


class TestInvalidOriginLifecycle:

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


class TestStrategySwitchAndUpdateLifecycle:

    @pytest.mark.parametrize('test_input, cmp_fn, expected_output',
                             [(['install', 'curse:transcriptor'],
                               str.startswith,
                               '✓ curse:transcriptor: installed'),
                              (['set', '--strategy=latest', 'curse:transcriptor'],
                               str.__eq__,
                               "✓ curse:transcriptor: 'strategy' set to 'latest'\n"),
                              (['update', 'curse:transcriptor'],
                               str.startswith,
                               '✓ curse:transcriptor: updated from'),
                              (['set', '--strategy=canonical', 'curse:transcriptor'],
                               str.__eq__,
                               "✓ curse:transcriptor: 'strategy' set to 'canonical'\n"),
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
