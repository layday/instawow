from functools import partial
import json

from click.testing import CliRunner
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
import pytest

from instawow import cli, utils


@pytest.fixture
def feed_pt():
    pipe_input = create_pipe_input()
    with create_app_session(input=pipe_input, output=DummyOutput()):
        yield pipe_input.send_text
    pipe_input.close()


@pytest.fixture
def run(monkeypatch, event_loop, iw_config, iw_web_client):
    def runner(self, awaitable):
        self.contextualise(web_client=iw_web_client)
        return event_loop.run_until_complete(awaitable)

    monkeypatch.setattr('instawow.manager.CliManager.run', runner)
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(iw_config.config_dir))
    yield partial(
        CliRunner().invoke,
        cli.main,
        catch_exceptions=False,
    )


@pytest.fixture
def molinari_and_run(run):
    run('install curse:molinari')
    yield run


@pytest.fixture
def faux_molinari_and_run(iw_config, run):
    molinari = iw_config.addon_dir / 'Molinari'
    molinari.mkdir()
    (molinari / 'Molinari.toc').write_text(
        '''\
## X-Curse-Project-ID: 20338
## X-WoWI-ID: 13188
'''
    )
    yield run


def test_valid_curse_pkg_lifecycle(run):
    assert run('install curse:molinari').output.startswith('✓ curse:molinari\n  installed')
    assert (
        run('install curse:molinari').output == '✗ curse:molinari\n  package already installed\n'
    )
    assert run('update curse:molinari').output == '✗ curse:molinari\n  package is up to date\n'
    assert run('remove curse:molinari').output == '✓ curse:molinari\n  removed\n'
    assert run('update curse:molinari').output == '✗ curse:molinari\n  package is not installed\n'
    assert run('remove curse:molinari').output == '✗ curse:molinari\n  package is not installed\n'


def test_valid_tukui_pkg_lifecycle(iw_config, run):
    assert run('install tukui:1').output.startswith('✓ tukui:1\n  installed')
    assert run('install tukui:1').output == '✗ tukui:1\n  package already installed\n'
    assert run('update tukui:1').output == '✗ tukui:1\n  package is up to date\n'
    assert run('remove tukui:1').output == '✓ tukui:1\n  removed\n'
    assert run('update tukui:1').output == '✗ tukui:1\n  package is not installed\n'
    assert run('remove tukui:1').output == '✗ tukui:1\n  package is not installed\n'
    if iw_config.is_retail:
        assert run('install tukui:-1').output.startswith('✓ tukui:-1\n  installed')
        assert run('install tukui:-1').output == '✗ tukui:-1\n  package already installed\n'
        assert run('update tukui:-1').output == '✗ tukui:-1\n  package is up to date\n'
        assert run('remove tukui:-1').output == '✓ tukui:-1\n  removed\n'
    else:
        assert run('install tukui:-1').output == '✗ tukui:-1\n  package does not exist\n'
    assert run('update tukui:-1').output == '✗ tukui:-1\n  package is not installed\n'
    assert run('remove tukui:-1').output == '✗ tukui:-1\n  package is not installed\n'


def test_valid_wowi_pkg_lifecycle(run):
    assert run('install wowi:13188-molinari').output.startswith(
        '✓ wowi:13188-molinari\n  installed'
    )
    assert (
        run('install wowi:13188-molinari').output
        == '✗ wowi:13188-molinari\n  package already installed\n'
    )
    assert (
        run('update wowi:13188-molinari').output
        == '✗ wowi:13188-molinari\n  package is up to date\n'
    )
    assert run('remove wowi:13188-molinari').output == '✓ wowi:13188-molinari\n  removed\n'
    assert (
        run('update wowi:13188-molinari').output
        == '✗ wowi:13188-molinari\n  package is not installed\n'
    )
    assert (
        run('remove wowi:13188-molinari').output
        == '✗ wowi:13188-molinari\n  package is not installed\n'
    )


def test_invalid_source_lifecycle(run):
    assert run('install foo:bar').output == '✗ foo:bar\n  package source is invalid\n'
    assert run('update foo:bar').output == '✗ foo:bar\n  package is not installed\n'
    assert run('remove foo:bar').output == '✗ foo:bar\n  package is not installed\n'


def test_nonexistent_addon_alias_lifecycle(run):
    assert (
        run('install curse:gargantuan-wigs').output
        == '✗ curse:gargantuan-wigs\n  package does not exist\n'
    )
    assert (
        run('update curse:gargantuan-wigs').output
        == '✗ curse:gargantuan-wigs\n  package is not installed\n'
    )
    assert (
        run('remove curse:gargantuan-wigs').output
        == '✗ curse:gargantuan-wigs\n  package is not installed\n'
    )


def test_reconciled_folder_conflict_on_install(run):
    assert run('install curse:molinari').output.startswith('✓ curse:molinari\n  installed')
    assert run('install wowi:13188-molinari').output == (
        '✗ wowi:13188-molinari\n'
        '  package folders conflict with installed package Molinari\n'
        '    (curse:20338)\n'
    )


def test_unreconciled_folder_conflict_on_install(iw_config, run):
    iw_config.addon_dir.joinpath('Molinari').mkdir()
    assert (
        run('install curse:molinari').output
        == "✗ curse:molinari\n  package folders conflict with 'Molinari'\n"
    )
    assert run('install --replace curse:molinari').output.startswith(
        '✓ curse:molinari\n  installed'
    )


def test_keep_folders_on_remove(iw_config, molinari_and_run):
    assert (
        molinari_and_run('remove --keep-folders curse:molinari').output
        == '✓ curse:molinari\n  removed\n'
    )
    assert iw_config.addon_dir.joinpath('Molinari').is_dir()


def test_install_with_curse_alias(run):
    assert run('install curse:molinari').output.startswith('✓ curse:molinari\n  installed')
    assert run('install curse:20338').output == '✗ curse:20338\n  package already installed\n'
    assert (
        run('install https://www.wowace.com/projects/molinari').output
        == '✗ curse:molinari\n  package already installed\n'
    )
    assert (
        run('install https://www.curseforge.com/wow/addons/molinari').output
        == '✗ curse:molinari\n  package already installed\n'
    )
    assert (
        run('install https://www.curseforge.com/wow/addons/molinari/download').output
        == '✗ curse:molinari\n  package already installed\n'
    )


def test_install_with_tukui_alias(iw_config, run):
    if iw_config.is_retail:
        assert run('install tukui:-1').output.startswith('✓ tukui:-1\n  installed')
        assert run('install tukui:tukui').output == '✗ tukui:tukui\n  package already installed\n'
        assert (
            run('install https://www.tukui.org/download.php?ui=tukui').output
            == '✗ tukui:tukui\n  package already installed\n'
        )
    else:
        assert run('install tukui:-1').output == '✗ tukui:-1\n  package does not exist\n'
        assert run('install tukui:tukui').output == '✗ tukui:tukui\n  package does not exist\n'
        assert (
            run('install https://www.tukui.org/download.php?ui=tukui').output
            == '✗ tukui:tukui\n  package does not exist\n'
        )
    assert run('install https://www.tukui.org/addons.php?id=1').output.startswith(
        '✓ tukui:1\n  installed'
    )
    assert run('install tukui:1').output == '✗ tukui:1\n  package already installed\n'


def test_install_with_wowi_alias(run):
    assert run('install wowi:13188').output.startswith('✓ wowi:13188\n  installed')
    assert (
        run('install wowi:13188-molinari').output
        == '✗ wowi:13188-molinari\n  package already installed\n'
    )
    assert (
        run('install https://www.wowinterface.com/downloads/landing.php?fileid=13188').output
        == '✗ wowi:13188\n  package already installed\n'
    )
    assert (
        run('install https://www.wowinterface.com/downloads/fileinfo.php?id=13188').output
        == '✗ wowi:13188\n  package already installed\n'
    )
    assert (
        run('install https://www.wowinterface.com/downloads/download13188-Molinari').output
        == '✗ wowi:13188\n  package already installed\n'
    )
    assert (
        run('install https://www.wowinterface.com/downloads/info13188-Molinari.html').output
        == '✗ wowi:13188\n  package already installed\n'
    )


def test_install_with_github_alias(run):
    assert run('install github:AdiAddons/AdiButtonAuras').output.startswith(
        '✓ github:AdiAddons/AdiButtonAuras\n  installed'
    )
    assert (
        run('install github:adiaddons/adibuttonauras').output
        == '✗ github:adiaddons/adibuttonauras\n  package already installed\n'
    )
    assert (
        run('install https://github.com/AdiAddons/AdiButtonAuras').output
        == '✗ github:AdiAddons/AdiButtonAuras\n  package already installed\n'
    )
    assert (
        run('install https://github.com/AdiAddons/AdiButtonAuras/releases').output
        == '✗ github:AdiAddons/AdiButtonAuras\n  package already installed\n'
    )
    assert (
        run('remove github:adiaddons/adibuttonauras').output
        == '✓ github:adiaddons/adibuttonauras\n  removed\n'
    )


def test_version_strategy_lifecycle(iw_config, run):
    assert (
        run('install curse:molinari').output == '✓ curse:molinari\n  installed 80300.66-Release\n'
    )
    assert (
        run('install --version foo curse:molinari').output
        == '✗ curse:molinari\n  package already installed\n'
    )
    assert run('update curse:molinari').output == '✗ curse:molinari\n  package is up to date\n'
    assert run('remove curse:molinari').output == '✓ curse:molinari\n  removed\n'
    assert (
        run('install --version foo curse:molinari').output
        == f"✗ curse:molinari\n  no files match {iw_config.game_flavour} using version strategy\n"
    )
    assert (
        run('install --version 80000.57-Release curse:molinari').output
        == '✓ curse:molinari\n  installed 80000.57-Release\n'
    )
    assert run('update').output == '✗ curse:molinari\n  package is pinned\n'
    assert run('update curse:molinari').output == '✗ curse:molinari\n  package is pinned\n'
    assert run('remove curse:molinari').output == '✓ curse:molinari\n  removed\n'


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


def test_configure__display_active_profile(iw_config, run):
    assert run('configure --active').output == iw_config.json(indent=2) + '\n'


def test_configure__create_new_profile(feed_pt, iw_config, run):
    feed_pt(f'{iw_config.addon_dir}\r\r')
    assert (
        run('-p foo configure').output
        == f'Configuration written to: {iw_config.config_dir / "profiles/foo/config.json"}\n'
    )


def test_configure__create_new_profile_promptless(monkeypatch, iw_config, run):
    monkeypatch.setenv('INSTAWOW_ADDON_DIR', str(iw_config.addon_dir))
    monkeypatch.setenv('INSTAWOW_GAME_FLAVOUR', iw_config.game_flavour.value)
    assert (
        run('-p foo configure --promptless').output
        == f'Configuration written to: {iw_config.config_dir / "profiles/foo/config.json"}\n'
    )


@pytest.mark.parametrize('options', ['', '--undo'])
def test_rollback__pkg_not_installed(run, options):
    assert (
        run(f'rollback {options} curse:molinari').output
        == '✗ curse:molinari\n  package is not installed\n'
    )


@pytest.mark.parametrize('options', ['', '--undo'])
def test_rollback__unsupported(run, options):
    assert run('install wowi:13188-molinari').exit_code == 0
    assert (
        run(f'rollback {options} wowi:13188-molinari').output
        == '✗ wowi:13188-molinari\n  source does not support rollback\n'
    )


def test_rollback__single_version(run):
    assert run('install curse:molinari').exit_code == 0
    assert (
        run(f'rollback curse:molinari').output
        == '✗ curse:molinari\n  cannot find older versions\n'
    )


def test_rollback__multiple_versions(feed_pt, run):
    assert run('install --version 80000.57-Release curse:molinari').exit_code == 0
    assert run('remove curse:molinari').exit_code == 0
    assert run('install curse:molinari').exit_code == 0
    feed_pt('\r\r')
    assert (
        run('rollback curse:molinari').output
        == '✓ curse:molinari\n  updated 80300.66-Release to 80000.57-Release\n'
    )


def test_rollback__multiple_versions_promptless(run):
    assert run('install --version 80000.57-Release curse:molinari').exit_code == 0
    assert run('remove curse:molinari').exit_code == 0
    assert run('install curse:molinari').exit_code == 0
    assert (
        run('rollback --version 80000.57-Release curse:molinari').output
        == '✓ curse:molinari\n  updated 80300.66-Release to 80000.57-Release\n'
    )


@pytest.mark.parametrize('options', ['', '--undo'])
def test_rollback__rollback_multiple_versions(feed_pt, run, options):
    test_rollback__multiple_versions(feed_pt, run)
    assert (
        run(f'rollback {options} curse:molinari').output
        == '✓ curse:molinari\n  updated 80000.57-Release to 80300.66-Release\n'
    )


def test_rollback__cannot_use_version_with_undo(run):
    result = run(f'rollback --version foo --undo curse:molinari')
    assert result.exit_code == 2
    assert 'Cannot use "--version" and "--undo" together' in result.output


def test_reconcile__list_unreconciled(faux_molinari_and_run):
    assert faux_molinari_and_run('reconcile --list-unreconciled').output == (
        # fmt: off
        'unreconciled\n'
        '------------\n'
        'Molinari    \n'
        # fmt: on
    )


def test_reconcile__auto_reconcile(faux_molinari_and_run):
    assert (
        faux_molinari_and_run('reconcile --auto').output
        == '✓ curse:molinari\n  installed 80300.66-Release\n'
    )


def test_reconcile__abort_interactive_reconciliation(feed_pt, faux_molinari_and_run):
    feed_pt('\x03')  # ^C
    assert faux_molinari_and_run('reconcile').output.endswith('Aborted!\n')


def test_reconcile__complete_interactive_reconciliation(feed_pt, faux_molinari_and_run):
    feed_pt('\r\r')
    assert faux_molinari_and_run('reconcile').output.endswith(
        '✓ curse:molinari\n  installed 80300.66-Release\n'
    )


def test_reconcile__reconciliation_complete(run):
    assert run('reconcile').output == 'No add-ons left to reconcile.\n'


def test_search__no_results(feed_pt, run):
    assert run('search ∅').output == 'No results found.\n'


def test_search__exit_without_selecting(feed_pt, run):
    feed_pt('\r')  # enter
    assert run('search molinari').output == ''


def test_search__exit_after_selection(feed_pt, run):
    feed_pt(' \rn')  # space, enter, "n"
    assert run('search molinari').output == ''


def test_search__install_directly_from_search(feed_pt, run):
    feed_pt(' \r\r')  # space, enter, enter
    assert (
        run('search molinari --source curse').output
        == '✓ curse:molinari\n  installed 80300.66-Release\n'
    )


def test_search__install_multiple(feed_pt, run):
    feed_pt(' \x1b[B \r\r')  # space, arrow down, space, enter, enter
    assert run('search molinari').output in {
        '''\
✓ curse:molinari
  installed 80300.66-Release
✗ wowi:13188-molinari
  package folders conflict with installed package Molinari
    (curse:20338)
''',
        '''\
✓ wowi:13188-molinari
  installed 80300.66-Release
✗ curse:molinari
  package folders conflict with installed package Molinari
    (wowi:13188)
''',
    }


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
    monkeypatch.setattr('click.launch', lambda url, wait=..., locate=...: ...)
    assert molinari_and_run(command).exit_code == exit_code


def test_can_list_with_substr_match(molinari_and_run):
    assert molinari_and_run('list mol').output == 'curse:molinari\n'
    assert molinari_and_run('list foo').output == ''
    assert molinari_and_run('list -f detailed mol').output.startswith('curse:molinari')
    (molinari,) = json.loads(molinari_and_run('list -f json mol').output)
    assert (molinari['source'], molinari['slug']) == ('curse', 'molinari')


def test_json_export_and_import(iw_config, molinari_and_run):
    export_json = iw_config.config_dir.parent / 'export.json'
    export_json.write_text(molinari_and_run('list -f json').output, encoding='utf-8')
    assert (
        molinari_and_run(f'install --import "{export_json}"').output
        == '✗ curse:molinari\n  package already installed\n'
    )


def test_show_version(run):
    assert run('--version').output == f'instawow, version {utils.get_version()}\n'


def test_plugin_hook_command_can_be_invoked(run):
    pytest.importorskip('instawow_test_plugin')
    assert run('foo').output == 'success!\n'
