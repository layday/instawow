from __future__ import annotations

import json
import shutil
from functools import partial
from textwrap import dedent
from unittest import mock

import click.testing
import prompt_toolkit.input
import pytest

from instawow.cli import cli
from instawow.config import ProfileConfig
from instawow.config._helpers import make_display_converter

pytestmark = pytest.mark.usefixtures(
    '_iw_config_ctx', '_iw_web_client_ctx', '_iw_mock_pt_progress_bar', '_iw_mock_asyncio_run'
)


_runner = click.testing.CliRunner()
run = partial(_runner.invoke, cli, catch_exceptions=False)


def install_masque():
    run('install curse:masque')


def pretend_install_masque(
    iw_profile_config: ProfileConfig,
):
    masque = iw_profile_config.addon_dir / 'Masque'
    masque.mkdir()
    (masque / 'Masque.toc').write_text(
        """\
## X-Curse-Project-ID: 13592
## X-WoWI-ID: 12097
""",
        encoding='utf-8',
    )


@pytest.mark.parametrize(
    'alias',
    [
        'curse:masque',
        'wowi:12097-masque',
        'tukui:tukui',
        'github:sfx-wow/masque',
    ],
)
def test_valid_pkg_lifecycle(
    alias: str,
):
    assert run(f'install {alias}').stdout.startswith(f'✓ {alias}\n  installed')
    assert run(f'install {alias}').stdout == f'✗ {alias}\n  package already installed\n'
    assert run(f'update {alias}').stdout == f'✗ {alias}\n  package is up to date\n'
    assert run(f'remove {alias}').stdout == f'✓ {alias}\n  removed\n'
    assert run(f'update {alias}').stdout == f'✗ {alias}\n  package is not installed\n'
    assert run(f'remove {alias}').stdout == f'✗ {alias}\n  package is not installed\n'


@pytest.mark.parametrize('alias', ['instawow:gargantuan-wigs'])
def test_nonexistent_pkg_lifecycle(
    alias: str,
):
    assert run(f'install {alias}').stdout == f'✗ {alias}\n  package does not exist\n'
    assert run(f'update {alias}').stdout == f'✗ {alias}\n  package is not installed\n'
    assert run(f'remove {alias}').stdout == f'✗ {alias}\n  package is not installed\n'


@pytest.mark.parametrize('iw_global_config_values', [None], indirect=True)
@pytest.mark.parametrize('alias', ['curse:masque'])
def test_disabled_source_lifecycle(
    alias: str,
):
    assert (
        run(f'install {alias}').stdout
        == f'✗ {alias}\n  package source is disabled: access token missing\n'
    )
    assert run(f'update {alias}').stdout == f'✗ {alias}\n  package is not installed\n'
    assert run(f'remove {alias}').stdout == f'✗ {alias}\n  package is not installed\n'


@pytest.mark.parametrize('alias', ['foo:bar'])
def test_invalid_source_lifecycle(
    alias: str,
):
    assert run(f'install {alias}').stdout == f'✗ :{alias}\n  package source is invalid\n'
    assert run(f'update {alias}').stdout == f'✗ :{alias}\n  package is not installed\n'
    assert run(f'remove {alias}').stdout == f'✗ {alias}\n  package is not installed\n'


def test_reconciled_folder_conflict_on_install():
    assert run('install curse:masque').stdout.startswith('✓ curse:masque\n  installed')
    assert run('install wowi:12097-masque').stdout == (
        '✗ wowi:12097-masque\n'
        '  package folders conflict with installed package Masque (curse:13592)\n'
    )


def test_unreconciled_folder_conflict_on_install(
    iw_profile_config: ProfileConfig,
):
    iw_profile_config.addon_dir.joinpath('Masque').mkdir()
    assert (
        run('install curse:masque').stdout
        == "✗ curse:masque\n  package folders conflict with 'Masque'\n"
    )
    assert run('install --replace curse:masque').stdout.startswith('✓ curse:masque\n  installed')


def test_keep_folders_on_remove(
    iw_profile_config: ProfileConfig,
):
    install_masque()
    assert run('remove --keep-folders curse:masque').stdout == '✓ curse:masque\n  removed\n'
    assert iw_profile_config.addon_dir.joinpath('Masque').is_dir()


def test_version_strategy_lifecycle():
    assert run('install curse:masque').stdout.startswith(
        '✓ curse:masque\n  installed 11.1.5_6454541'
    )
    assert (
        run('install curse:masque#version_eq=foo').stdout
        == '✗ curse:masque\n  package already installed\n'
    )
    assert run('update curse:masque').stdout == '✗ curse:masque\n  package is up to date\n'
    assert run('update curse:masque#version_eq=11.0.2').stdout == dedent(
        """\
        ✓ curse:masque
          updated 11.1.5_6454541 to 11.0.2_5810397 with new strategies:
            version_eq='11.0.2_5810397'
        """
    )
    assert run('remove curse:masque').stdout == '✓ curse:masque\n  removed\n'
    assert run('install curse:masque#version_eq=foo').stdout == dedent(
        """\
        ✗ curse:masque
          no files are available for download
        """
    )
    assert (
        run('install curse:masque#version_eq=11.0.2').stdout
        == '✓ curse:masque\n  installed 11.0.2_5810397\n'
    )
    assert run('update').stdout == '✗ curse:masque\n  package is pinned\n'
    assert run('update curse:masque#=').stdout == dedent(
        """\
        ✓ curse:masque
          updated 11.0.2_5810397 to 11.1.5_6454541 with new strategies:
            version_eq=None
        """
    )
    assert run('remove curse:masque').stdout == '✓ curse:masque\n  removed\n'


def test_install_options():
    assert run('install curse:masque#any_release_type,any_flavour').stdout == dedent(
        """\
        ✓ curse:masque
          installed 11.1.7-Beta-2_6725716
        """
    )


@pytest.mark.parametrize('step', [1, -1])
def test_install_order_is_respected(
    step: int,
):
    assert run(
        'install '
        + ' '.join(
            [
                'curse:masque',
                'curse:masque#version_eq=11.0.2',
            ][::step]
        )
    ).stdout == dedent(
        f"""\
        ✓ curse:masque
          installed {'11.1.5_6454541' if step == 1 else '11.0.2_5810397'}
        ✗ curse:masque
          package folders conflict with installed package Masque (curse:13592)
        """
    )


def test_install_invalid_defn():
    result = run('install foo')
    assert result.exit_code == 2
    assert result.stderr.endswith("Error: Invalid value for '[ADDONS]...': foo\n")


def test_install_dry_run():
    assert run('install --dry-run curse:masque').stdout == dedent(
        """\
        ✓ curse:masque
          would have installed 11.1.5_6454541
        """
    )


def test_debug_config(
    iw_profile_config: ProfileConfig,
):
    assert (
        run('debug config').stdout
        == json.dumps(make_display_converter().unstructure(iw_profile_config), indent=2) + '\n'
    )


def test_debug_profile(
    iw_profile_config: ProfileConfig,
):
    assert (
        run('debug profiles').stdout
        == json.dumps(
            make_display_converter().unstructure(
                iw_profile_config.iter_profiles(iw_profile_config.global_config), list[str]
            ),
            indent=2,
        )
        + '\n'
    )


def test_debug_sources():
    import cattrs.preconf.json

    from instawow.definitions import SourceMetadata

    json_converter = cattrs.preconf.json.make_converter()

    output = run('debug sources').stdout
    source_metadata = json_converter.loads(output, list[SourceMetadata])
    assert len(source_metadata) > 1


@pytest.mark.parametrize('command', ['configure', 'list'], ids=['explicit', 'implicit'])
def test_configure__create_new_profile(
    monkeypatch: pytest.MonkeyPatch,
    iw_pt_input: prompt_toolkit.input.PipeInput,
    iw_profile_config: ProfileConfig,
    command: str,
):
    # In case there is a WoW installation in the test environment.
    monkeypatch.setattr('instawow.wow_installations.find_installations', lambda: iter([]))

    iw_pt_input.send_text(f'{iw_profile_config.addon_dir}\r\rY\r')
    assert run(f'-p foo {command}').stdout == (
        'Generate an access token for GitHub to avoid being rate limited. You\n'
        'are only allowed to perform 60 requests an hour without one.\n'
        'Navigate to https://github.com/login/device and paste the code below:\n'
        '  WDJB-MJHT\n'
        'Waiting...\n'
        'Configuration written to:\n'
        f'  {iw_profile_config.global_config.dirs.config / "config.json"}\n'
        f'  {iw_profile_config.global_config.dirs.config / "profiles/foo/config.json"}\n'
    )


def test_configure__update_existing_profile_interactively(
    iw_pt_input: prompt_toolkit.input.PipeInput,
    iw_profile_config: ProfileConfig,
):
    iw_pt_input.send_text('Y\r')
    assert run('configure global_config.auto_update_check').stdout == (
        'Configuration written to:\n'
        f'  {iw_profile_config.global_config.dirs.config / "config.json"}\n'
        f'  {iw_profile_config.global_config.dirs.config / "profiles/__default__/config.json"}\n'
    )


def test_configure__update_existing_profile_directly(
    iw_profile_config: ProfileConfig,
):
    assert run('configure global_config.auto_update_check=0').stdout == (
        'Configuration written to:\n'
        f'  {iw_profile_config.global_config.dirs.config / "config.json"}\n'
        f'  {iw_profile_config.global_config.dirs.config / "profiles/__default__/config.json"}\n'
    )


def test_erase_profile(
    iw_profile_config: ProfileConfig,
    iw_pt_input: prompt_toolkit.input.PipeInput,
):
    assert iw_profile_config.config_path.exists()
    iw_pt_input.send_text('Y\r')
    assert run('profile erase').stdout == 'Profile erased.\n'
    assert not iw_profile_config.config_path.exists()


@pytest.mark.parametrize('options', ['', '--undo'])
def test_rollback__pkg_not_installed(
    options: str,
):
    assert (
        run(f'rollback {options} curse:masque').stdout
        == '✗ curse:masque\n  package is not installed\n'
    )


@pytest.mark.parametrize('options', ['', '--undo'])
def test_rollback__unsupported(
    options: str,
):
    assert run('install wowi:12097-masque').exit_code == 0
    assert (
        run(f'rollback {options} wowi:12097-masque').stdout
        == '✗ wowi:12097-masque\n  strategies are not valid for source: version_eq\n'
    )


def test_rollback__single_version():
    assert run('install curse:masque').exit_code == 0
    assert run('rollback curse:masque').stdout == '✗ curse:masque\n  cannot find older versions\n'


def test_rollback__multiple_versions(
    iw_pt_input: prompt_toolkit.input.PipeInput,
):
    assert run('install curse:masque#version_eq=11.0.2').exit_code == 0
    assert run('remove curse:masque').exit_code == 0
    assert run('install curse:masque').exit_code == 0
    iw_pt_input.send_text('\r\r')
    assert run('rollback curse:masque').stdout == dedent(
        """\
        ✓ curse:masque
          updated 11.1.5_6454541 to 11.0.2_5810397 with new strategies:
            version_eq='11.0.2_5810397'
        """
    )


@pytest.mark.parametrize('options', ['', '--undo'])
def test_rollback__rollback_multiple_versions(
    iw_pt_input: prompt_toolkit.input.PipeInput,
    options: str,
):
    assert run('install curse:masque').exit_code == 0
    assert run('remove curse:masque').exit_code == 0
    assert run('install curse:masque#version_eq=11.0.2').exit_code == 0
    iw_pt_input.send_text('\r\r')
    assert run(f'rollback {options} curse:masque').stdout == dedent(
        """\
        ✓ curse:masque
          updated 11.0.2_5810397 to 11.1.5_6454541 with new strategies:
            version_eq=None
        """
        if options == '--undo'
        else """\
        ✓ curse:masque
          updated 11.0.2_5810397 to 11.1.5_6454541
        """
    )


def test_reconcile__list_unreconciled(
    iw_profile_config: ProfileConfig,
):
    pretend_install_masque(iw_profile_config)
    assert run('reconcile --list-unreconciled').stdout == dedent(
        """\
        unreconciled
        ------------
        Masque      \

        """
    )


def test_reconcile_leftovers(
    iw_pt_input: prompt_toolkit.input.PipeInput,
    iw_profile_config: ProfileConfig,
):
    pretend_install_masque(iw_profile_config)
    iw_pt_input.send_text('sss')  # Skip
    assert run('reconcile').stdout.endswith(
        dedent(
            """\
            unreconciled
            ------------
            Masque      \

            """
        )
    )


def test_reconcile__auto_reconcile(
    iw_profile_config: ProfileConfig,
):
    pretend_install_masque(iw_profile_config)
    assert run('reconcile --auto').stdout == dedent(
        """\
        ✓ github:sfx-wow/masque
          installed 11.1.5
        """
    )


def test_reconcile__abort_interactive_reconciliation(
    iw_pt_input: prompt_toolkit.input.PipeInput,
    iw_profile_config: ProfileConfig,
):
    pretend_install_masque(iw_profile_config)
    iw_pt_input.send_text('\x03')  # ^C
    assert run('reconcile').stderr.endswith('Aborted!\n')


def test_reconcile__complete_interactive_reconciliation(
    iw_pt_input: prompt_toolkit.input.PipeInput,
    iw_profile_config: ProfileConfig,
):
    pretend_install_masque(iw_profile_config)
    iw_pt_input.send_text('\ry')
    assert run('reconcile').stdout.endswith(
        dedent(
            """\
            ✓ github:sfx-wow/masque
              installed 11.1.5
            """
        )
    )


def test_reconcile__reconciliation_complete():
    assert run('reconcile').stdout == 'No add-ons left to reconcile.\n'


def test_rereconcile(
    iw_pt_input: prompt_toolkit.input.PipeInput,
):
    install_masque()
    iw_pt_input.send_text('\ry')
    assert run('rereconcile').stdout == dedent(
        """\
        ✓ curse:masque
          removed
        ✓ github:sfx-wow/masque
          installed 11.1.5
        """
    )


def test_rereconcile_with_args(
    iw_pt_input: prompt_toolkit.input.PipeInput,
):
    install_masque()

    iw_pt_input.send_text('\ry')
    assert run('rereconcile foo').stdout == ''

    iw_pt_input.send_text('\ry')
    assert run('rereconcile masque').stdout == dedent(
        """\
        ✓ curse:masque
          removed
        ✓ github:sfx-wow/masque
          installed 11.1.5
        """
    )


def test_search__no_results():
    assert run('search ∅').stdout == 'No results found.\n'


def test_search__exit_without_selecting(
    iw_pt_input: prompt_toolkit.input.PipeInput,
):
    iw_pt_input.send_text('\r')  # enter
    assert run('search masque').stdout == (
        'Nothing was selected; select add-ons with <space> and confirm by pressing <enter>.\n'
    )


def test_search__exit_after_selection(
    iw_pt_input: prompt_toolkit.input.PipeInput,
):
    iw_pt_input.send_text(' \rn')  # space, enter, "n"
    assert run('search masque').stdout == ''


def test_search__install_one(
    iw_pt_input: prompt_toolkit.input.PipeInput,
):
    iw_pt_input.send_text(' \ry')  # space, enter, enter
    assert run('search masque --source curse').stdout == dedent(
        """\
        ✓ curse:masque
          installed 11.1.5_6454541
        """
    )


def test_search__install_multiple_conflicting(
    iw_pt_input: prompt_toolkit.input.PipeInput,
):
    iw_pt_input.send_text(' \x1b[B \ry')  # space, arrow down, space, enter, enter
    assert run('search masque').stdout == dedent(
        """\
        ✓ wowi:12097
          installed 11.1.7-Beta-2
        ✗ curse:masque
          package folders conflict with installed package Masque (wowi:12097)
        """
    )


def test_changelog_output_installed_convert():
    install_masque()
    stdout = (
        'curse:masque:\n  11.1.5' if shutil.which('pandoc') else 'curse:masque:\n  <h2>11.1.5</h2>'
    )
    assert run('view-changelog curse:masque').stdout.startswith(stdout)


def test_changelog_output_installed_no_convert():
    install_masque()
    assert run('view-changelog --no-convert curse:masque').stdout.startswith(
        'curse:masque:\n  <h2>11.1.5</h2>'
    )


def test_changelog_output_not_installed():
    assert run('view-changelog curse:masque').stdout == ''


def test_changelog_output_argless():
    install_masque()
    assert run('view-changelog').stdout.startswith('curse:masque:')


def test_changelog_output_remote():
    assert run('view-changelog --remote curse:masque').stdout.startswith('curse:masque:')


def test_changelog_warning_if_no_pandoc():
    stderr = (
        ''
        if shutil.which('pandoc')
        else '! pandoc is not installed; changelogs will not be converted\n'
    )
    assert run('view-changelog curse:masque').stderr == stderr


@pytest.mark.parametrize(
    ('command', 'exit_code'),
    [
        ('list mas', 0),
        ('info foo', 0),
        ('reveal mas', 0),
        ('reveal foo', 1),
    ],
)
def test_exit_codes_with_substr_match(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    exit_code: int,
):
    install_masque()
    monkeypatch.setattr('instawow._utils.file.reveal_folder', mock.MagicMock())
    assert run(command).exit_code == exit_code


def test_can_list_with_substr_match():
    install_masque()
    assert run('list mas').stdout == 'curse:masque\n'
    assert run('list foo').stdout == ''
    assert run('list -f detailed mas').stdout.startswith('curse:masque')
    (masque,) = json.loads(run('list -f json mas').stdout)
    assert (masque['source'], masque['slug']) == ('curse', 'masque')


def test_json_export():
    install_masque()
    output = run('list -f json').stdout
    assert json.loads(output)[0]['name'] == 'Masque'


def test_show_version():
    from instawow._version import get_version

    assert run('--version').stdout == f'instawow, version {get_version()}\n'


def test_plugin_hook_command_can_be_invoked():
    pytest.importorskip('instawow_test_plugin')
    assert run('plugins foo').stdout == 'success!\n'


# Skip loading the `_iw_web_client_ctx` fixture
# to allow deleting the cache on Windows.
@pytest.mark.parametrize('_iw_web_client_ctx', [None])
def test_clear_cache(
    iw_profile_config: ProfileConfig,
):
    assert iw_profile_config.global_config.dirs.cache.is_dir()
    assert run('cache clear').exit_code == 0
    assert not iw_profile_config.global_config.dirs.cache.is_dir()
