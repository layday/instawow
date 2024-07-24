from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Callable
from functools import partial
from textwrap import dedent
from typing import TypeAlias
from unittest import mock

import click.testing
import prompt_toolkit.application
import prompt_toolkit.input
import prompt_toolkit.output
import pytest

from instawow.cli import cli
from instawow.config import ProfileConfig

Run: TypeAlias = Callable[[str], click.testing.Result]


@pytest.fixture(autouse=True, scope='module')
def _mock_pt_progress_bar():
    with pytest.MonkeyPatch.context() as context:
        context.setattr(
            'prompt_toolkit.shortcuts.progress_bar.ProgressBar',
            mock.MagicMock(),
        )
        yield


@pytest.fixture
def pt_input():
    with (
        prompt_toolkit.input.create_pipe_input() as pipe_input,
        prompt_toolkit.application.create_app_session(
            input=pipe_input, output=prompt_toolkit.output.DummyOutput()
        ),
    ):
        yield pipe_input


@pytest.fixture
async def run(
    monkeypatch: pytest.MonkeyPatch,
    iw_profile_config: object,
):
    loop = asyncio.get_running_loop()
    monkeypatch.setattr('asyncio.run', loop.run_until_complete)

    return partial(click.testing.CliRunner().invoke, cli, catch_exceptions=False)


@pytest.fixture
def install_molinari_and_run(
    run: Run,
):
    run('install curse:molinari')
    return run


@pytest.fixture
def pretend_install_molinari_and_run(
    iw_profile_config: ProfileConfig,
    run: Run,
):
    molinari = iw_profile_config.addon_dir / 'Molinari'
    molinari.mkdir()
    (molinari / 'Molinari.toc').write_text(
        """\
## X-Curse-Project-ID: 20338
## X-WoWI-ID: 13188
"""
    )
    return run


@pytest.mark.parametrize(
    'alias',
    [
        'curse:molinari',
        'wowi:13188-molinari',
        'tukui:tukui',
        'github:p3lim-wow/Molinari',
    ],
)
def test_valid_pkg_lifecycle(
    run: Run,
    alias: str,
):
    assert run(f'install {alias}').output.startswith(f'✓ {alias}\n  installed')
    assert run(f'install {alias}').output == f'✗ {alias}\n  package already installed\n'
    assert run(f'update {alias}').output == f'✗ {alias}\n  package is up to date\n'
    assert run(f'remove {alias}').output == f'✓ {alias}\n  removed\n'
    assert run(f'update {alias}').output == f'✗ {alias}\n  package is not installed\n'
    assert run(f'remove {alias}').output == f'✗ {alias}\n  package is not installed\n'


@pytest.mark.parametrize('alias', ['instawow:gargantuan-wigs'])
def test_nonexistent_pkg_lifecycle(
    run: Run,
    alias: str,
):
    assert run(f'install {alias}').output == f'✗ {alias}\n  package does not exist\n'
    assert run(f'update {alias}').output == f'✗ {alias}\n  package is not installed\n'
    assert run(f'remove {alias}').output == f'✗ {alias}\n  package is not installed\n'


@pytest.mark.parametrize('iw_global_config_values', [None], indirect=True)
@pytest.mark.parametrize('alias', ['curse:molinari'])
def test_disabled_source_lifecycle(
    run: Run,
    alias: str,
):
    assert run(f'install {alias}').output == f'✗ {alias}\n  access token is not configured\n'
    assert run(f'update {alias}').output == f'✗ {alias}\n  package is not installed\n'
    assert run(f'remove {alias}').output == f'✗ {alias}\n  package is not installed\n'


@pytest.mark.parametrize('alias', ['foo:bar'])
def test_invalid_source_lifecycle(
    run: Run,
    alias: str,
):
    assert run(f'install {alias}').output == f'✗ :{alias}\n  package source is invalid\n'
    assert run(f'update {alias}').output == f'✗ :{alias}\n  package is not installed\n'
    assert run(f'remove {alias}').output == f'✗ :{alias}\n  package is not installed\n'


def test_reconciled_folder_conflict_on_install(
    run: Run,
):
    assert run('install curse:molinari').output.startswith('✓ curse:molinari\n  installed')
    assert run('install wowi:13188-molinari').output == (
        '✗ wowi:13188-molinari\n'
        '  package folders conflict with installed package Molinari\n'
        '    (curse:20338)\n'
    )


def test_unreconciled_folder_conflict_on_install(
    iw_profile_config: ProfileConfig,
    run: Run,
):
    iw_profile_config.addon_dir.joinpath('Molinari').mkdir()
    assert (
        run('install curse:molinari').output
        == "✗ curse:molinari\n  package folders conflict with 'Molinari'\n"
    )
    assert run('install --replace curse:molinari').output.startswith(
        '✓ curse:molinari\n  installed'
    )


def test_keep_folders_on_remove(
    iw_profile_config: ProfileConfig,
    install_molinari_and_run: Run,
):
    assert (
        install_molinari_and_run('remove --keep-folders curse:molinari').output
        == '✓ curse:molinari\n  removed\n'
    )
    assert iw_profile_config.addon_dir.joinpath('Molinari').is_dir()


def test_version_strategy_lifecycle(
    run: Run,
):
    assert run('install curse:molinari').output.startswith(
        '✓ curse:molinari\n  installed 100205.111-Release_5090686'
    )
    assert (
        run('install curse:molinari#version_eq=foo').output
        == '✗ curse:molinari\n  package already installed\n'
    )
    assert run('update curse:molinari').output == '✗ curse:molinari\n  package is up to date\n'
    assert run('update curse:molinari#version_eq=100005.97-Release').output == dedent(
        """\
        ✓ curse:molinari
          updated 100205.111-Release_5090686 to 100005.97-Release_4419396 with
            new strategies: version_eq='100005.97-Release_4419396'
        """
    )
    assert run('remove curse:molinari').output == '✓ curse:molinari\n  removed\n'
    assert run('install curse:molinari#version_eq=foo').output == dedent(
        """\
        ✗ curse:molinari
          no files are available for download
        """
    )
    assert (
        run('install curse:molinari#version_eq=100005.97-Release').output
        == '✓ curse:molinari\n  installed 100005.97-Release_4419396\n'
    )
    assert run('update').output == '✗ curse:molinari\n  package is pinned\n'
    assert run('update curse:molinari#=').output == dedent(
        """\
        ✓ curse:molinari
          updated 100005.97-Release_4419396 to 100205.111-Release_5090686 with
            new strategies: version_eq=None
        """
    )
    assert run('remove curse:molinari').output == '✓ curse:molinari\n  removed\n'


def test_install_options(
    run: Run,
):
    assert run('install curse:molinari#any_release_type,any_flavour').output == dedent(
        """\
        ✓ curse:molinari
          installed 100205.111-Release_5090686
        """
    )


@pytest.mark.parametrize('step', [1, -1])
def test_install_order_is_respected(
    run: Run,
    step: int,
):
    assert run(
        'install '
        + ' '.join(
            [
                'curse:molinari',
                'curse:molinari#version_eq=100005.97-Release',
            ][::step]
        )
    ).output == dedent(
        f"""\
        ✓ curse:molinari
          installed {'100205.111-Release_5090686' if step == 1 else '100005.97-Release_4419396'}
        ✗ curse:molinari
          package folders conflict with installed package Molinari
            (curse:20338)
        """
    )


def test_install_invalid_defn(
    run: Run,
):
    result = run('install foo')
    assert result.exit_code == 2
    assert result.output.endswith("Error: Invalid value for '[ADDONS]...': foo\n")


def test_install_dry_run(
    run: Run,
):
    assert run('install --dry-run curse:molinari').output == dedent(
        """\
        ✓ curse:molinari
          would have installed 100205.111-Release_5090686
        """
    )


def test_debug_config(
    iw_profile_config: ProfileConfig,
    run: Run,
):
    assert (
        run('debug config').output
        == json.dumps(iw_profile_config.unstructure_for_display(), indent=2) + '\n'
    )


def test_debug_sources(
    run: Run,
):
    import cattrs.preconf.json

    from instawow.definitions import SourceMetadata

    json_converter = cattrs.preconf.json.make_converter()

    output = run('debug sources').output
    source_metadata = json_converter.loads(output, list[SourceMetadata])
    assert len(source_metadata) > 1


@pytest.mark.parametrize('command', ['configure', 'list'], ids=['explicit', 'implicit'])
def test_configure__create_new_profile(
    monkeypatch: pytest.MonkeyPatch,
    pt_input: prompt_toolkit.input.PipeInput,
    iw_profile_config: ProfileConfig,
    run: Run,
    command: str,
):
    # In case there is a WoW installation in the test environment.
    monkeypatch.setattr('instawow.wow_installations.find_installations', lambda: iter([]))

    pt_input.send_text(f'{iw_profile_config.addon_dir}\r\rY\r')
    assert run(f'-p foo {command}').output == (
        'Generating an access token for GitHub is recommended to avoid being\n'
        'rate limited.  You may only perform 60 requests an hour without an\n'
        'access token.\n'
        'Navigate to https://github.com/login/device and paste the code below:\n'
        '  WDJB-MJHT\n'
        'Waiting...\n'
        'Configuration written to:\n'
        f'  {iw_profile_config.global_config.config_dir / "config.json"}\n'
        f'  {iw_profile_config.global_config.config_dir / "profiles/foo/config.json"}\n'
    )


def test_configure__update_existing_profile_interactively(
    pt_input: prompt_toolkit.input.PipeInput,
    iw_profile_config: ProfileConfig,
    run: Run,
):
    pt_input.send_text('Y\r')
    assert run('configure global_config.auto_update_check').output == (
        'Configuration written to:\n'
        f'  {iw_profile_config.global_config.config_dir / "config.json"}\n'
        f'  {iw_profile_config.global_config.config_dir / "profiles/__default__/config.json"}\n'
    )


def test_configure__update_existing_profile_directly(
    iw_profile_config: ProfileConfig,
    run: Run,
):
    assert run('configure global_config.auto_update_check=0').output == (
        'Configuration written to:\n'
        f'  {iw_profile_config.global_config.config_dir / "config.json"}\n'
        f'  {iw_profile_config.global_config.config_dir / "profiles/__default__/config.json"}\n'
    )


@pytest.mark.parametrize('options', ['', '--undo'])
def test_rollback__pkg_not_installed(
    run: Run,
    options: str,
):
    assert (
        run(f'rollback {options} curse:molinari').output
        == '✗ curse:molinari\n  package is not installed\n'
    )


@pytest.mark.parametrize('options', ['', '--undo'])
def test_rollback__unsupported(
    run: Run,
    options: str,
):
    assert run('install wowi:13188-molinari').exit_code == 0
    assert (
        run(f'rollback {options} wowi:13188-molinari').output
        == '✗ wowi:13188-molinari\n  strategies are not valid for source: version_eq\n'
    )


def test_rollback__single_version(
    run: Run,
):
    assert run('install curse:molinari').exit_code == 0
    assert (
        run('rollback curse:molinari').output == '✗ curse:molinari\n  cannot find older versions\n'
    )


def test_rollback__multiple_versions(
    pt_input: prompt_toolkit.input.PipeInput,
    run: Run,
):
    assert run('install curse:molinari#version_eq=100005.97-Release').exit_code == 0
    assert run('remove curse:molinari').exit_code == 0
    assert run('install curse:molinari').exit_code == 0
    pt_input.send_text('\r\r')
    assert run('rollback curse:molinari').output == dedent(
        """\
        ✓ curse:molinari
          updated 100205.111-Release_5090686 to 100005.97-Release_4419396 with
            new strategies: version_eq='100005.97-Release_4419396'
        """
    )


@pytest.mark.parametrize('options', ['', '--undo'])
def test_rollback__rollback_multiple_versions(
    pt_input: prompt_toolkit.input.PipeInput,
    run: Run,
    options: str,
):
    assert run('install curse:molinari').exit_code == 0
    assert run('remove curse:molinari').exit_code == 0
    assert run('install curse:molinari#version_eq=100005.97-Release').exit_code == 0
    pt_input.send_text('\r\r')
    assert run(f'rollback {options} curse:molinari').output == dedent(
        """\
        ✓ curse:molinari
          updated 100005.97-Release_4419396 to 100205.111-Release_5090686 with
            new strategies: version_eq=None
        """
        if options == '--undo'
        else """\
        ✓ curse:molinari
          updated 100005.97-Release_4419396 to 100205.111-Release_5090686
        """
    )


def test_reconcile__list_unreconciled(
    pretend_install_molinari_and_run: Run,
):
    assert (
        pretend_install_molinari_and_run('reconcile --list-unreconciled').output
        == (
            'unreconciled\n'  # fmt: skip
            '------------\n'
            'Molinari    \n'
        )
    )


def test_reconcile_leftovers(
    pt_input: prompt_toolkit.input.PipeInput,
    pretend_install_molinari_and_run: Run,
):
    pt_input.send_text('sss')  # Skip
    assert pretend_install_molinari_and_run(
        'reconcile'
    ).output.endswith(
        'unreconciled\n'  # fmt: skip
        '------------\n'
        'Molinari    \n'
    )


def test_reconcile__auto_reconcile(
    pretend_install_molinari_and_run: Run,
):
    assert pretend_install_molinari_and_run('reconcile --auto').output == dedent(
        """\
        ✓ github:p3lim-wow/molinari
          installed 100205.111-Release
        """
    )


def test_reconcile__abort_interactive_reconciliation(
    pt_input: prompt_toolkit.input.PipeInput,
    pretend_install_molinari_and_run: Run,
):
    pt_input.send_text('\x03')  # ^C
    assert pretend_install_molinari_and_run('reconcile').output.endswith('Aborted!\n')


def test_reconcile__complete_interactive_reconciliation(
    pt_input: prompt_toolkit.input.PipeInput,
    pretend_install_molinari_and_run: Run,
):
    pt_input.send_text('\ry')
    assert pretend_install_molinari_and_run('reconcile').output.endswith(
        dedent(
            """\
            ✓ github:p3lim-wow/molinari
              installed 100205.111-Release
            """
        )
    )


def test_reconcile__reconciliation_complete(
    run: Run,
):
    assert run('reconcile').output == 'No add-ons left to reconcile.\n'


def test_rereconcile(
    pt_input: prompt_toolkit.input.PipeInput,
    install_molinari_and_run: Run,
):
    pt_input.send_text('\ry')
    assert install_molinari_and_run('rereconcile').output == dedent(
        """\
        ✓ curse:molinari
          removed
        ✓ github:p3lim-wow/molinari
          installed 100205.111-Release
        """
    )


def test_rereconcile_with_args(
    pt_input: prompt_toolkit.input.PipeInput,
    install_molinari_and_run: Run,
):
    pt_input.send_text('\ry')
    assert install_molinari_and_run('rereconcile foo').output == ''

    pt_input.send_text('\ry')
    assert install_molinari_and_run('rereconcile molinari').output == dedent(
        """\
        ✓ curse:molinari
          removed
        ✓ github:p3lim-wow/molinari
          installed 100205.111-Release
        """
    )


def test_search__no_results(
    run: Run,
):
    assert run('search ∅').output == 'No results found.\n'


def test_search__exit_without_selecting(
    pt_input: prompt_toolkit.input.PipeInput,
    run: Run,
):
    pt_input.send_text('\r')  # enter
    assert run('search molinari').output == (
        'Nothing was selected; select add-ons with <space> and confirm by pressing <enter>.\n'
    )


def test_search__exit_after_selection(
    pt_input: prompt_toolkit.input.PipeInput,
    run: Run,
):
    pt_input.send_text(' \rn')  # space, enter, "n"
    assert run('search molinari').output == ''


def test_search__install_one(
    pt_input: prompt_toolkit.input.PipeInput,
    run: Run,
):
    pt_input.send_text(' \ry')  # space, enter, enter
    assert run('search molinari --source curse').output == dedent(
        """\
        ✓ curse:molinari
          installed 100205.111-Release_5090686
        """
    )


def test_search__install_multiple_conflicting(
    pt_input: prompt_toolkit.input.PipeInput,
    run: Run,
):
    pt_input.send_text(' \x1b[B \ry')  # space, arrow down, space, enter, enter
    assert run('search molinari').output == dedent(
        """\
        ✓ github:p3lim-wow/molinari
          installed 100205.111-Release
        ✗ wowi:13188
          package folders conflict with installed package Molinari
            (github:388670)
        """
    )


def test_changelog_output_installed_convert(
    install_molinari_and_run: Run,
):
    output = (
        'curse:molinari:\n  Changes in 90200.82-Release:'
        if shutil.which('pandoc')
        else 'curse:molinari:\n  <h3>Changes in'
    )
    assert install_molinari_and_run('view-changelog curse:molinari').output.startswith(output)


def test_changelog_output_installed_no_convert(
    install_molinari_and_run: Run,
):
    assert install_molinari_and_run(
        'view-changelog --no-convert curse:molinari'
    ).output.startswith('curse:molinari:\n  <h3>Changes in')


def test_changelog_output_not_installed(
    run: Run,
):
    assert run('view-changelog curse:molinari').output == ''


def test_changelog_output_argless(
    install_molinari_and_run: Run,
):
    assert install_molinari_and_run('view-changelog').output.startswith('curse:molinari:')


def test_changelog_output_remote(
    run: Run,
):
    assert run('view-changelog --remote curse:molinari').output.startswith('curse:molinari:')


@pytest.mark.parametrize(
    ('command', 'exit_code'),
    [
        ('list mol', 0),
        ('info foo', 0),
        ('reveal mol', 0),
        ('reveal foo', 1),
    ],
)
def test_exit_codes_with_substr_match(
    monkeypatch: pytest.MonkeyPatch,
    install_molinari_and_run: Run,
    command: str,
    exit_code: int,
):
    monkeypatch.setattr('instawow._utils.file.reveal_folder', lambda *_, **__: ...)
    assert install_molinari_and_run(command).exit_code == exit_code


def test_can_list_with_substr_match(
    install_molinari_and_run: Run,
):
    assert install_molinari_and_run('list mol').output == 'curse:molinari\n'
    assert install_molinari_and_run('list foo').output == ''
    assert install_molinari_and_run('list -f detailed mol').output.startswith('curse:molinari')
    (molinari,) = json.loads(install_molinari_and_run('list -f json mol').output)
    assert (molinari['source'], molinari['slug']) == ('curse', 'molinari')


def test_json_export(
    install_molinari_and_run: Run,
):
    output = install_molinari_and_run('list -f json').output
    assert json.loads(output)[0]['name'] == 'Molinari'


def test_show_version(
    run: Run,
):
    from instawow._version_check import get_version

    assert run('--version').output == f'instawow, version {get_version()}\n'


def test_plugin_hook_command_can_be_invoked(
    run: Run,
):
    pytest.importorskip('instawow_test_plugin')
    assert run('plugins foo').output == 'success!\n'
