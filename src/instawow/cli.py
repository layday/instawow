from __future__ import annotations

from collections.abc import Callable, Generator, Iterable, Iterator, Sequence, Set
from datetime import datetime
from enum import Enum
from functools import partial
from itertools import chain
from pathlib import Path
import textwrap
from typing import overload

import click

from . import __version__, manager as managers, models, results as R
from .config import Config, Flavour, setup_logging
from .plugins import load_plugins
from .resolvers import Defn, MultiPkgModel, Strategy
from .utils import cached_property, is_outdated, tabulate, uniq


class Report:
    SUCCESS_SYMBOL = click.style('✓', fg='green')
    FAILURE_SYMBOL = click.style('✗', fg='red')
    WARNING_SYMBOL = click.style('!', fg='blue')

    def __init__(
        self,
        results: Iterable[tuple[Defn, R.ManagerResult]],
        filter_fn: Callable[[R.ManagerResult], bool] = lambda _: True,
    ) -> None:
        self.results = list(results)
        self.filter_fn = filter_fn

    @property
    def exit_code(self) -> int:
        return any(
            isinstance(r, (R.ManagerError, R.InternalError)) and self.filter_fn(r)
            for _, r in self.results
        )

    @classmethod
    def _result_type_to_symbol(cls, result: R.ManagerResult) -> str:
        if isinstance(result, R.InternalError):
            return cls.WARNING_SYMBOL
        elif isinstance(result, R.ManagerError):
            return cls.FAILURE_SYMBOL
        else:
            return cls.SUCCESS_SYMBOL

    def __str__(self) -> str:
        return '\n'.join(
            f'{self._result_type_to_symbol(r)} {click.style(a.to_uri(), bold=True)}\n'
            f'{textwrap.fill(r.message, initial_indent=" " * 2, subsequent_indent=" " * 4)}'
            for a, r in self.results
            if self.filter_fn(r)
        )

    def generate(self) -> None:
        manager_wrapper: ManagerWrapper | None = click.get_current_context().obj
        if manager_wrapper and manager_wrapper.m.config.auto_update_check:
            outdated, new_version = manager_wrapper.m.run(is_outdated())
            if outdated:
                click.echo(f'{self.WARNING_SYMBOL} instawow-{new_version} is available')

        report = str(self)
        if report:
            click.echo(report)

    def generate_and_exit(self) -> None:
        self.generate()
        ctx = click.get_current_context()
        ctx.exit(self.exit_code)


def _set_mac_multiprocessing_start_method() -> None:
    import sys

    # Reference: https://github.com/indygreg/PyOxidizer/issues/111#issuecomment-808834727

    if getattr(sys, 'frozen', False) and sys.platform == 'darwin':
        import multiprocessing

        multiprocessing.set_start_method('fork')


def _override_asyncio_loop_policy() -> None:
    # The proactor event loop which became the default loop on Windows
    # in Python 3.8 is causing issues with aiohttp.
    # See https://github.com/aio-libs/aiohttp/issues/4324
    import asyncio

    policy = getattr(asyncio, 'WindowsSelectorEventLoopPolicy', None)
    if policy:
        asyncio.set_event_loop_policy(policy())


def _set_asyncio_debug(debug: bool) -> None:
    # This is the least obtrusive way to enable debugging in asyncio.
    # Reference: https://docs.python.org/3/library/asyncio-dev.html#debug-mode
    if debug:
        import os

        os.environ['PYTHONASYNCIODEBUG'] = '1'


class ManagerWrapper:
    def __init__(self, ctx: click.Context) -> None:
        self.ctx = ctx

    @cached_property
    def m(self) -> managers.CliManager:
        _set_mac_multiprocessing_start_method()
        _override_asyncio_loop_policy()
        _set_asyncio_debug(self.ctx.params['log_level'] == 'DEBUG')

        try:
            config = Config.read(self.ctx.params['profile']).ensure_dirs()
        except FileNotFoundError:
            config = self.ctx.invoke(configure, promptless=False)

        setup_logging(config, self.ctx.params['log_level'])

        manager = managers.CliManager.from_config(config)
        return manager


def _with_manager(
    fn: Callable[..., object]
) -> Callable[[click.Context, click.Parameter, object], object]:
    def wrapper(ctx: click.Context, __: click.Parameter, value: object) -> object:
        assert ctx.obj
        return fn(ctx.obj.m, value)

    return wrapper


class EnumParam(click.Choice):
    def __init__(
        self,
        choice_enum: type[Enum],
        excludes: Set[Enum] = frozenset(),
        case_sensitive: bool = True,
    ) -> None:
        self.choice_enum = choice_enum
        super().__init__(
            choices=[c.name for c in choice_enum if c not in excludes],
            case_sensitive=case_sensitive,
        )

    def convert(
        self, value: str, param: click.Parameter | None, ctx: click.Context | None
    ) -> Enum:
        parent_result = super().convert(value, param, ctx)
        return self.choice_enum[parent_result]


def _register_plugin_commands(group: click.Group) -> click.Group:
    plugin_hook = load_plugins()
    additional_commands = (c for g in plugin_hook.instawow_add_commands() for c in g)
    for command in additional_commands:
        group.add_command(command)
    return group


def _set_log_level(_: click.Context, __: click.Parameter, value: bool) -> str:
    return 'DEBUG' if value else 'INFO'


@_register_plugin_commands
@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.version_option(__version__, prog_name=__package__)
@click.option(
    '--debug',
    'log_level',
    is_flag=True,
    default=False,
    callback=_set_log_level,
    help='Log more things.',
)
@click.option(
    '--profile',
    '-p',
    default='__default__',
    help='Activate the specified profile.',
)
@click.pass_context
def main(ctx: click.Context, log_level: str, profile: str) -> None:
    "Add-on manager for World of Warcraft."
    ctx.obj = ManagerWrapper(ctx)


@overload
def parse_into_defn(manager: managers.Manager, value: str, *, raise_invalid: bool = True) -> Defn:
    ...


@overload
def parse_into_defn(
    manager: managers.Manager, value: list[str], *, raise_invalid: bool = True
) -> list[Defn]:
    ...


def parse_into_defn(
    manager: managers.Manager, value: str | list[str], *, raise_invalid: bool = True
) -> Defn | list[Defn]:
    if not isinstance(value, str):
        defns = (parse_into_defn(manager, v, raise_invalid=raise_invalid) for v in value)
        return uniq(defns)

    pair = manager.pair_uri(value)
    if not pair:
        if raise_invalid:
            raise click.BadParameter(value)

        pair = '*', value
    return Defn(*pair)


def parse_into_defn_with_strategy(
    manager: managers.Manager, value: Sequence[tuple[Strategy, str]]
) -> Iterator[Defn]:
    defns = parse_into_defn(manager, [d for _, d in value])
    return map(Defn.with_strategy, defns, (s for s, _ in value))


def parse_into_defn_with_version(
    manager: managers.Manager, value: Sequence[tuple[str, str]]
) -> Iterator[Defn]:
    defns = parse_into_defn(manager, [d for _, d in value])
    return map(Defn.with_version, defns, (v for v, _ in value))


def combine_addons(
    fn: Callable[[managers.Manager, object], Iterable[Defn]],
    ctx: click.Context,
    __: click.Parameter,
    value: object,
) -> None:
    addons: list[Defn] = ctx.params.setdefault('addons', [])
    if value:
        assert ctx.obj
        addons.extend(fn(ctx.obj.m, value))


_EXCLUDED_STRATEGIES = frozenset({Strategy.default, Strategy.version})


@main.command()
@click.argument(
    'addons', nargs=-1, callback=partial(combine_addons, parse_into_defn), expose_value=False
)
@click.option(
    '--with-strategy',
    '-s',
    multiple=True,
    type=(EnumParam(Strategy, _EXCLUDED_STRATEGIES), str),
    expose_value=False,
    callback=partial(combine_addons, parse_into_defn_with_strategy),
    metavar='<STRATEGY ADDON>...',
    help='A strategy followed by an add-on definition.  '
    'The strategy is one of: '
    f'{", ".join(s for s in Strategy if s not in _EXCLUDED_STRATEGIES)}.',
)
@click.option(
    '--version',
    multiple=True,
    type=(str, str),
    expose_value=False,
    callback=partial(combine_addons, parse_into_defn_with_version),
    metavar='<VERSION ADDON>...',
    help='A version followed by an add-on definition.',
)
@click.option('--replace', is_flag=True, default=False, help='Replace unreconciled add-ons.')
@click.pass_obj
def install(obj: ManagerWrapper, addons: Sequence[Defn], replace: bool) -> None:
    "Install add-ons."
    if not addons:
        raise click.UsageError(
            'You must provide at least one of "ADDONS", "--with-strategy" or "--version"'
        )

    results = obj.m.run(obj.m.install(addons, replace))
    Report(results.items()).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, callback=_with_manager(parse_into_defn))
@click.pass_obj
def update(obj: ManagerWrapper, addons: Sequence[Defn]) -> None:
    "Update installed add-ons."

    def filter_results(result: R.ManagerResult):
        # Hide packages from output if they are up to date
        # and ``update`` was invoked without args,
        # provided that they are not pinned
        if addons or not isinstance(result, R.PkgUpToDate):
            return True
        else:
            return result.is_pinned

    results = obj.m.run(
        obj.m.update(
            addons or list(map(Defn.from_pkg, obj.m.database.query(models.Pkg).all())), False
        )
    )
    Report(results.items(), filter_results).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, required=True, callback=_with_manager(parse_into_defn))
@click.option(
    '--keep-folders',
    is_flag=True,
    default=False,
    help="Do not delete the add-on folders.",
)
@click.pass_obj
def remove(obj: ManagerWrapper, addons: Sequence[Defn], keep_folders: bool) -> None:
    "Remove add-ons."
    results = obj.m.run(obj.m.remove(addons, keep_folders))
    Report(results.items()).generate_and_exit()


@main.command()
@click.argument('addon', callback=_with_manager(parse_into_defn))
@click.option(
    '--version',
    help='Version to roll back to.',
)
@click.option(
    '--undo',
    is_flag=True,
    default=False,
    help='Undo rollback by reinstalling an add-on using the default strategy.',
)
@click.pass_obj
def rollback(obj: ManagerWrapper, addon: Defn, version: str | None, undo: bool) -> None:
    "Roll an add-on back to an older version."
    from .prompts import Choice, select

    manager = obj.m

    if version and undo:
        raise click.UsageError('Cannot use "--version" and "--undo" together')

    pkg = manager.get_pkg(addon)
    if not pkg:
        Report([(addon, R.PkgNotInstalled())]).generate_and_exit()
        return  # pragma: no cover

    if not manager.resolvers[pkg.source].supports_rollback:
        Report(
            [(addon, R.PkgFileUnavailable('source does not support rollback'))]
        ).generate_and_exit()

    if undo:
        Report(manager.run(manager.update([addon], True)).items()).generate_and_exit()

    reconstructed_defn = Defn.from_pkg(pkg)
    if version:
        selection = version
    else:
        versions = pkg.logged_versions
        if len(versions) <= 1:
            Report(
                [(addon, R.PkgFileUnavailable('cannot find older versions'))]
            ).generate_and_exit()

        choices = [
            Choice(
                [('', v.version)],
                value=v.version,
                disabled='installed version' if v.version == pkg.version else None,
            )
            for v in versions
        ]
        selection = select(
            f'Select version of {reconstructed_defn.to_uri()} for rollback', choices
        ).unsafe_ask()

    Report(
        manager.run(manager.update([reconstructed_defn.with_version(selection)], True)).items()
    ).generate_and_exit()


@main.command()
@click.option(
    '--auto', '-a', is_flag=True, default=False, help='Do not ask for user confirmation.'
)
@click.option(
    '--list-unreconciled', is_flag=True, default=False, help='List unreconciled add-ons and exit.'
)
@click.pass_obj
def reconcile(obj: ManagerWrapper, auto: bool, list_unreconciled: bool) -> None:
    "Reconcile pre-installed add-ons."
    from .matchers import (
        AddonFolder,
        get_unreconciled_folder_set,
        match_addon_names_with_folder_names,
        match_folder_name_subsets,
        match_toc_source_ids,
    )
    from .prompts import PkgChoice, confirm, select, skip

    preamble = textwrap.dedent(
        '''\
        Use the arrow keys to navigate, <o> to open an add-on in your browser,
        enter to make a selection and <s> to skip to the next item.

        Versions that differ from the installed version or differ between
        choices are highlighted in purple.

        The reconciler will perform three passes in decreasing order of accuracy,
        looking to match source IDs and add-on names in TOC files, and folders.

        Selected add-ons will be reinstalled.

        You can also run `reconcile` in promptless mode by passing
        the `--auto` flag.  In this mode, add-ons will be reconciled
        without user input.
        '''
    )

    manager = obj.m

    def prompt_one(addons: list[AddonFolder], pkgs: list[models.Pkg]) -> Defn | tuple[()]:
        def construct_choice(pkg: models.Pkg):
            defn = Defn.from_pkg(pkg)
            title = [
                ('', f'{defn.to_uri()}=='),
                ('class:highlight-sub' if highlight_version else '', pkg.version),
            ]
            return PkgChoice(title, pkg=pkg, value=defn)

        # Highlight version if there's multiple of them
        highlight_version = len({i.version for i in chain(addons, pkgs)}) > 1
        choices = list(chain(map(construct_choice, pkgs), (skip,)))
        addon = addons[0]
        # Using 'unsafe_ask' to let ^C bubble up
        selection = select(f'{addon.name} [{addon.version or "?"}]', choices).unsafe_ask()
        return selection

    def prompt(groups: Sequence[tuple[list[AddonFolder], list[Defn]]]) -> Iterable[Defn]:
        uniq_defns = uniq(d for _, b in groups for d in b)
        results = manager.run(manager.resolve(uniq_defns))
        for addons, defns in groups:
            shortlist: list[models.Pkg] = list(filter(models.is_pkg, (results[d] for d in defns)))
            if shortlist:
                selection = Defn.from_pkg(shortlist[0]) if auto else prompt_one(addons, shortlist)
                selection and (yield selection)

    def match_all() -> Generator[list[Defn], frozenset[AddonFolder], None]:
        # Match in order of increasing heuristicitivenessitude
        for fn in (
            match_toc_source_ids,
            match_folder_name_subsets,
            match_addon_names_with_folder_names,
        ):
            groups = manager.run(fn(manager, (yield [])))
            yield list(prompt(groups))

    leftovers = get_unreconciled_folder_set(manager)
    if list_unreconciled:
        table_rows = [('unreconciled',), *((f.name,) for f in sorted(leftovers))]
        click.echo(tabulate(table_rows))
        return
    elif not leftovers:
        click.echo('No add-ons left to reconcile.')
        return

    if not auto:
        click.echo(preamble)

    matcher = match_all()
    for _ in matcher:  # Skip over consumer yields
        selections = matcher.send(leftovers)
        if selections and (auto or confirm('Install selected add-ons?').unsafe_ask()):
            results = manager.run(manager.install(selections, replace=True))
            Report(results.items()).generate()

        leftovers = get_unreconciled_folder_set(manager)

    if leftovers:
        click.echo()
        table_rows = [('unreconciled',), *((f.name,) for f in sorted(leftovers))]
        click.echo(tabulate(table_rows))


def _concat_search_terms(_: click.Context, __: click.Parameter, value: tuple[str, ...]) -> str:
    return ' '.join(value)


@main.command()
@click.argument('search-terms', nargs=-1, required=True, callback=_concat_search_terms)
@click.option(
    '--limit',
    '-l',
    default=10,
    type=click.IntRange(1, 20, clamp=True),
    help='A number to limit results to.',
)
@click.option(
    '--source',
    'sources',
    multiple=True,
    help='A source to search in.  Repeatable.',
)
@click.pass_context
def search(ctx: click.Context, search_terms: str, limit: int, sources: Sequence[str]) -> None:
    "Search for add-ons to install."
    from .prompts import PkgChoice, checkbox, confirm

    assert ctx.obj
    manager: managers.CliManager = ctx.obj.m

    entries = manager.run(manager.search(search_terms, limit, frozenset(sources) or None))
    defns = [Defn(e.source, e.id) for e in entries]
    pkgs = (
        (d.with_(alias=r.slug), r)
        for d, r in manager.run(manager.resolve(defns)).items()
        if models.is_pkg(r)
    )
    choices = [PkgChoice(f'{p.name}  ({d.to_uri()}=={p.version})', d, pkg=p) for d, p in pkgs]
    if choices:
        selections = checkbox('Select add-ons to install', choices=choices).unsafe_ask()
        if selections and confirm('Install selected add-ons?').unsafe_ask():
            ctx.invoke(install, addons=selections)
    else:
        click.echo('No results found.')


class ListFormats(str, Enum):
    simple = 'simple'
    detailed = 'detailed'
    json = 'json'


@main.command('list')
@click.argument(
    'addons', nargs=-1, callback=_with_manager(partial(parse_into_defn, raise_invalid=False))
)
@click.option(
    '--format',
    '-f',
    'output_format',
    type=EnumParam(ListFormats),
    default=ListFormats.simple,
    show_default=True,
    help='Change the output format.',
)
@click.pass_obj
def list_installed(
    obj: ManagerWrapper, addons: Sequence[Defn], output_format: ListFormats
) -> None:
    "List installed add-ons."
    from sqlalchemy import and_, or_

    def format_deps(pkg: models.Pkg):
        return (
            (d.with_(alias=p.slug) if p else d).to_uri()
            for e in pkg.deps
            for d in (Defn(pkg.source, e.id),)
            for p in (obj.m.get_pkg(d),)
        )

    pkgs = (
        obj.m.database.query(models.Pkg)
        .filter(
            or_(
                *(
                    models.Pkg.slug.contains(d.alias)
                    if d.source == '*'
                    else and_(
                        models.Pkg.source == d.source,
                        or_(models.Pkg.id == d.alias, models.Pkg.slug == d.alias),
                    )
                    for d in addons
                )
            )
            if addons
            else True
        )
        .order_by(models.Pkg.source, models.Pkg.name)
        .all()
    )
    if output_format is ListFormats.json:
        click.echo(MultiPkgModel.parse_obj(pkgs).json(indent=2))
    elif output_format is ListFormats.detailed:
        formatter = click.HelpFormatter(max_width=99)
        for pkg in pkgs:
            with formatter.section(Defn.from_pkg(pkg).to_uri()):
                formatter.write_dl(
                    (
                        ('Name', pkg.name),
                        ('Description', textwrap.shorten(pkg.description, 280)),
                        ('URL', pkg.url),
                        ('Version', pkg.version),
                        ('Date published', pkg.date_published.isoformat(' ', 'minutes')),
                        ('Folders', ', '.join(f.name for f in pkg.folders)),
                        ('Dependencies', ', '.join(format_deps(pkg))),
                        ('Options', f'{{"strategy": "{pkg.options.strategy}"}}'),
                    )
                )
        click.echo(formatter.getvalue(), nl=False)
    else:
        click.echo(''.join(f'{Defn.from_pkg(p).to_uri()}\n' for p in pkgs), nl=False)


@main.command(hidden=True)
@click.argument('addon', callback=_with_manager(partial(parse_into_defn, raise_invalid=False)))
@click.pass_context
def info(ctx: click.Context, addon: Defn) -> None:
    "Alias of `list -f detailed`."
    ctx.invoke(list_installed, addons=(addon,), output_format=ListFormats.detailed)


@main.command()
@click.argument('addon', callback=_with_manager(partial(parse_into_defn, raise_invalid=False)))
@click.pass_obj
def reveal(obj: ManagerWrapper, addon: Defn) -> None:
    "Bring an add-on up in your file manager."
    pkg = obj.m.get_pkg(addon, partial_match=True)
    if pkg:
        click.launch(str(obj.m.config.addon_dir / pkg.folders[0].name), locate=True)
    else:
        Report([(addon, R.PkgNotInstalled())]).generate_and_exit()


@main.command()
@click.argument('addon', callback=_with_manager(partial(parse_into_defn, raise_invalid=False)))
@click.pass_obj
def view_changelog(obj: ManagerWrapper, addon: Defn) -> None:
    "View the changelog of an installed add-on."
    pkg = obj.m.get_pkg(addon, partial_match=True)
    if pkg:
        click.echo_via_pager(obj.m.run(obj.m.get_changelog(pkg.changelog_url)))
    else:
        Report([(addon, R.PkgNotInstalled())]).generate_and_exit()


def _show_active_config(ctx: click.Context, __: click.Parameter, value: bool) -> None:
    if value:
        assert ctx.obj
        click.echo(ctx.obj.m.config.json(indent=2))
        ctx.exit()


@main.command()
@click.option(
    '--active',
    'show_active',
    is_flag=True,
    default=False,
    expose_value=False,
    is_eager=True,
    callback=_show_active_config,
    help='Show the active configuration and exit.',
)
@click.option(
    '--promptless',
    is_flag=True,
    default=False,
    help='Do not prompt for input and derive the configuration from the environment.',
)
@click.pass_context
def configure(ctx: click.Context, promptless: bool) -> Config:
    "Configure instawow."
    if promptless:
        constructor = Config
    else:
        from .prompts import PydanticValidator, path, select

        addon_dir = path(
            'Add-on directory:',
            only_directories=True,
            validate=PydanticValidator(Config, 'addon_dir'),
        ).unsafe_ask()
        game_flavour = select(
            'Game flavour:',
            choices=list(Flavour),
            initial_choice=Config.infer_flavour(addon_dir),
        ).unsafe_ask()
        constructor = partial(Config, addon_dir=addon_dir, game_flavour=game_flavour)

    config = constructor(profile=ctx.find_root().params['profile']).write()
    click.echo(f'Configuration written to: {config.config_file}')
    return config


@main.group('weakauras-companion')
def _weakauras_group() -> None:
    "Manage your WeakAuras."


@_weakauras_group.command('build')
@click.pass_obj
def build_weakauras_companion(obj: ManagerWrapper) -> None:
    "Build the WeakAuras Companion add-on."
    from .wa_updater import BuilderConfig, WaCompanionBuilder

    config = BuilderConfig()
    obj.m.run(WaCompanionBuilder(obj.m, config).build())


@_weakauras_group.command('list')
@click.pass_obj
def list_installed_wago_auras(obj: ManagerWrapper) -> None:
    "List WeakAuras installed from Wago."
    from .wa_updater import BuilderConfig, WaCompanionBuilder

    config = BuilderConfig()
    aura_groups = WaCompanionBuilder(obj.m, config).extract_installed_auras()
    installed_auras = sorted(
        (g.filename, textwrap.fill(a.id, width=30, max_lines=1), a.url)
        for g in aura_groups
        for v in g.__root__.values()
        for a in v
        if not a.parent
    )
    click.echo(tabulate([('in file', 'name', 'URL'), *installed_auras]))


def _parse_datetime(_: click.Context, __: click.Parameter, value: str | None) -> datetime | None:
    if value is not None:
        return datetime.fromisoformat(value)


@main.command(hidden=True)
@click.argument('filename', type=click.Path(dir_okay=False))
@click.option('--age-cutoff', callback=_parse_datetime)
def generate_catalogue(filename: str, age_cutoff: datetime | None) -> None:
    "Generate the master catalogue."
    import asyncio

    from .resolvers import Catalogue

    catalogue = asyncio.run(Catalogue.collate(age_cutoff))
    file = Path(filename)
    file.write_text(
        catalogue.json(indent=2),
        encoding='utf-8',
    )
    file.with_suffix(f'.compact{file.suffix}').write_text(
        catalogue.json(separators=(',', ':')),
        encoding='utf-8',
    )


@main.command(hidden=True)
@click.option(
    '--log-to-stderr', is_flag=True, default=False, help="Output log to stderr for debugging."
)
@click.pass_context
def gui(ctx: click.Context, log_to_stderr: bool) -> None:
    "Fire up the GUI."
    from instawow_gui import InstawowApp

    log_level = ctx.find_root().params['log_level']
    _set_mac_multiprocessing_start_method()
    _override_asyncio_loop_policy()
    _set_asyncio_debug(log_level == 'DEBUG')

    if not log_to_stderr:
        dummy_config = Config.get_dummy_config(profile='__jsonrpc__').ensure_dirs()
        setup_logging(dummy_config, log_level)

    InstawowApp(version=__version__).main_loop()
