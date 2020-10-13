from __future__ import annotations

from datetime import datetime
import enum
from functools import partial
from itertools import chain
from pathlib import Path
from textwrap import dedent, fill
from typing import (
    TYPE_CHECKING,
    AbstractSet,
    Callable,
    FrozenSet,
    Generator,
    Generic,
    Iterable,
    List,
    Optional as O,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
    overload,
)

import click

from . import exceptions as E, models
from .config import Config, setup_logging
from .resolvers import Defn, MultiPkgModel, Strategy
from .utils import TocReader, cached_property, get_version, is_outdated, tabulate, uniq

if TYPE_CHECKING:
    from .manager import CliManager

    _R = TypeVar('_R')

_EnumT = TypeVar('_EnumT', bound=enum.Enum)


class Report:
    SUCCESS_SYMBOL = click.style('✓', fg='green')
    FAILURE_SYMBOL = click.style('✗', fg='red')
    WARNING_SYMBOL = click.style('!', fg='blue')

    def __init__(
        self,
        results: Iterable[Tuple[Defn, E.ManagerResult]],
        filter_fn: Callable[[E.ManagerResult], bool] = lambda _: True,
    ):
        self.results = list(results)
        self.filter_fn = filter_fn

    @property
    def exit_code(self) -> int:
        return any(
            isinstance(r, (E.ManagerError, E.InternalError)) and self.filter_fn(r)
            for _, r in self.results
        )

    @classmethod
    def _result_type_to_symbol(cls, result: E.ManagerResult) -> str:
        if isinstance(result, E.InternalError):
            return cls.WARNING_SYMBOL
        elif isinstance(result, E.ManagerError):
            return cls.FAILURE_SYMBOL
        else:
            return cls.SUCCESS_SYMBOL

    def __str__(self) -> str:
        return '\n'.join(
            f'{self._result_type_to_symbol(r)} {click.style(str(a), bold=True)}\n'
            + fill(r.message, initial_indent=' ' * 2, subsequent_indent=' ' * 4)
            for a, r in self.results
            if self.filter_fn(r)
        )

    def generate(self):
        manager: CliManager = click.get_current_context().obj.m
        if manager.config.auto_update_check:
            outdated, new_version = manager.run(is_outdated())
            if outdated:
                click.echo(f'{self.WARNING_SYMBOL} instawow-{new_version} is available')

        report = str(self)
        if report:
            click.echo(report)

    def generate_and_exit(self):
        self.generate()
        ctx = click.get_current_context()
        ctx.exit(self.exit_code)


def _override_loop_policy() -> None:
    # The proactor event loop which became the default on Windows in 3.8 is
    # tripping up aiohttp<4.  See https://github.com/aio-libs/aiohttp/issues/4324
    import asyncio

    policy = getattr(asyncio, 'WindowsSelectorEventLoopPolicy', None)
    if policy:
        asyncio.set_event_loop_policy(policy())


class ManagerWrapper:
    def __init__(self, ctx: click.Context):
        self.ctx = ctx

    @cached_property
    def m(self) -> CliManager:
        from .manager import CliManager

        try:
            config = Config.read(self.ctx.params['profile']).ensure_dirs()
        except FileNotFoundError:
            config = self.ctx.invoke(configure)
        setup_logging(config, self.ctx.params['log_level'])
        _override_loop_policy()
        manager = CliManager.from_config(config)
        return manager


class PathParam(click.Path):
    def coerce_path_result(self, value: str) -> Path:  # type: ignore
        return Path(value)


class EnumParam(click.Choice, Generic[_EnumT]):
    def __init__(
        self,
        choice_enum: Type[_EnumT],
        excludes: AbstractSet[_EnumT] = frozenset(),
        case_sensitive: bool = True,
    ) -> None:
        self.choice_enum = choice_enum
        super().__init__(
            choices=[c.name for c in choice_enum if c not in excludes],
            case_sensitive=case_sensitive,
        )

    def convert(self, value: str, param: O[click.Parameter], ctx: O[click.Context]) -> _EnumT:
        parent_result = super().convert(value, param, ctx)
        return self.choice_enum[parent_result]


def _callbackify(fn: Callable[..., _R]) -> Callable[[click.Context, click.Parameter, object], _R]:
    return lambda c, _, v: fn(c.obj.m, v)


@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.version_option(get_version(), prog_name=__package__)
@click.option(
    '--debug',
    'log_level',
    is_flag=True,
    default=False,
    callback=lambda _, __, v: 'DEBUG' if v else 'INFO',
    help='Log more things.',
)
@click.option(
    '--profile',
    '-p',
    default='__default__',
    help='Activate the specified profile.',
)
@click.pass_context
def main(ctx: click.Context, log_level: str, profile: str):
    "Add-on manager for World of Warcraft."
    ctx.obj = ManagerWrapper(ctx)


@overload
def parse_into_defn(manager: CliManager, value: str, *, raise_invalid: bool = True) -> Defn:
    ...


@overload
def parse_into_defn(
    manager: CliManager, value: List[str], *, raise_invalid: bool = True
) -> List[Defn]:
    ...


def parse_into_defn(
    manager: CliManager, value: Union[str, List[str]], *, raise_invalid: bool = True
) -> Union[Defn, List[Defn]]:
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
    manager: CliManager, value: Sequence[Tuple[Strategy, str]]
) -> Iterable[Defn]:
    defns = parse_into_defn(manager, [d for _, d in value])
    return map(Defn.with_strategy, defns, (s for s, _ in value))


def parse_into_defn_with_version(
    manager: CliManager, value: Sequence[Tuple[str, str]]
) -> Iterable[Defn]:
    defns = parse_into_defn(manager, [d for _, d in value])
    return map(Defn.with_version, defns, (v for v, _ in value))


def parse_into_defn_from_json_file(manager: CliManager, path: Path) -> Iterable[Defn]:
    faux_pkgs = MultiPkgModel.parse_file(path, encoding='utf-8')
    return map(Defn.from_pkg, faux_pkgs.__root__)


def combine_addons(
    fn: Callable[[CliManager, object], List[Defn]],
    ctx: click.Context,
    click_param: click.Parameter,
    value: object,
) -> None:
    addons: List[Defn] = ctx.params.setdefault('addons', [])
    if value:
        addons.extend(fn(ctx.obj.m, value))


excluded_strategies = {Strategy.default, Strategy.version}


@main.command()
@click.argument(
    'addons', nargs=-1, callback=partial(combine_addons, parse_into_defn), expose_value=False
)
@click.option(
    '--import',
    '-i',
    type=PathParam(dir_okay=False, exists=True),
    expose_value=False,
    callback=partial(combine_addons, parse_into_defn_from_json_file),
    help='Install add-ons from the output of `list -f json`.',
)
@click.option(
    '--with-strategy',
    '-s',
    multiple=True,
    type=(EnumParam(Strategy, excluded_strategies), str),
    expose_value=False,
    callback=partial(combine_addons, parse_into_defn_with_strategy),
    metavar='<STRATEGY ADDON>...',
    help='A strategy followed by an add-on definition.  '
    'The strategies are: '
    f'{", ".join(s.name for s in Strategy if s not in excluded_strategies)}.',
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
            'You must provide at least one of "ADDONS", "--with-strategy", '
            '"--version" or "--import"'
        )

    results = obj.m.run(obj.m.install(addons, replace))
    Report(results.items()).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, callback=_callbackify(parse_into_defn))
@click.pass_obj
def update(obj: ManagerWrapper, addons: Sequence[Defn]) -> None:
    "Update installed add-ons."

    def filter_results(result: E.ManagerResult):
        # Hide packages from output if they are up to date
        # and ``update`` was invoked without args,
        # provided that they are not pinned
        if addons or not isinstance(result, E.PkgUpToDate):
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
@click.argument('addons', nargs=-1, required=True, callback=_callbackify(parse_into_defn))
@click.pass_obj
def remove(obj: ManagerWrapper, addons: Sequence[Defn]) -> None:
    "Remove add-ons."
    results = obj.m.run(obj.m.remove(addons))
    Report(results.items()).generate_and_exit()


@main.command()
@click.argument('addon', callback=_callbackify(parse_into_defn))
@click.option(
    '--undo',
    is_flag=True,
    default=False,
    help='Undo rollback by reinstalling an add-on using the default strategy.',
)
@click.pass_context
def rollback(ctx: click.Context, addon: Defn, undo: bool) -> None:
    "Roll an add-on back to an older version."
    from .prompts import Choice, select

    manager: CliManager = ctx.obj.m
    limit = 10

    pkg = manager.get_pkg(addon)
    if not pkg:
        Report([(addon, E.PkgNotInstalled())]).generate_and_exit()
        return  # noop

    if not manager.resolvers[pkg.source].supports_rollback:
        Report(
            [(addon, E.PkgFileUnavailable('source does not support rollback'))]
        ).generate_and_exit()

    if undo:
        Report(manager.run(manager.update([addon], True)).items()).generate_and_exit()

    versions = (
        manager.database.query(models.PkgVersionLog)
        .filter(
            models.PkgVersionLog.pkg_source == pkg.source, models.PkgVersionLog.pkg_id == pkg.id
        )
        .order_by(models.PkgVersionLog.install_time.desc())
        .limit(limit)
        .all()
    )
    if len(versions) <= 1:
        Report([(addon, E.PkgFileUnavailable('cannot find older versions'))]).generate_and_exit()

    reconstructed_defn = Defn.from_pkg(pkg)
    choices = [
        Choice(
            [('', v.version)],
            value=v.version,
            disabled='installed version' if v.version == pkg.version else None,
        )
        for v in versions
    ]
    selection: str = select(
        f'Select version of {reconstructed_defn} for rollback', choices
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
@click.pass_context
def reconcile(ctx: click.Context, auto: bool, list_unreconciled: bool) -> None:
    "Reconcile pre-installed add-ons."
    from .matchers import (
        AddonFolder,
        get_folder_set,
        match_dir_names,
        match_toc_ids,
        match_toc_names,
    )
    from .models import is_pkg
    from .prompts import PkgChoice, confirm, select, skip

    preamble = dedent(
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

    manager: CliManager = ctx.obj.m

    def prompt_one(addons: List[AddonFolder], pkgs: List[models.Pkg]) -> Union[Defn, Tuple[()]]:
        def construct_choice(pkg: models.Pkg):
            defn = Defn.from_pkg(pkg)
            title = [
                ('', f'=={defn}'),
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

    def prompt(groups: Sequence[Tuple[List[AddonFolder], List[Defn]]]) -> Iterable[Defn]:
        uniq_defns = uniq(d for _, b in groups for d in b)
        results = manager.run(manager.resolve(uniq_defns))
        for addons, defns in groups:
            shortlist: List[models.Pkg] = list(filter(is_pkg, (results[d] for d in defns)))
            if shortlist:
                selection = Defn.from_pkg(shortlist[0]) if auto else prompt_one(addons, shortlist)
                selection and (yield selection)

    def match_all() -> Generator[List[Defn], FrozenSet[AddonFolder], None]:
        # Match in order of increasing heuristicitivenessitude
        for fn in (
            match_toc_ids,
            match_dir_names,
            match_toc_names,
        ):
            groups = manager.run(fn(manager, (yield [])))
            yield list(prompt(groups))

    leftovers = get_folder_set(manager)
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

        leftovers = get_folder_set(manager)

    if leftovers:
        click.echo()
        table_rows = [('unreconciled',), *((f.name,) for f in sorted(leftovers))]
        click.echo(tabulate(table_rows))


@main.command()
@click.argument('search-terms', nargs=-1, required=True, callback=lambda _, __, v: ' '.join(v))
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

    manager: CliManager = ctx.obj.m

    pkgs = manager.run(manager.search(search_terms, limit, frozenset(sources) or None))
    if pkgs:
        choices = [PkgChoice(f'{p.name}  ({d}=={p.version})', d, pkg=p) for d, p in pkgs.items()]
        selections = checkbox('Select add-ons to install', choices=choices).unsafe_ask()
        if selections and confirm('Install selected add-ons?').unsafe_ask():
            ctx.invoke(install, addons=selections)
    else:
        click.echo('No results found.')


class ListFormats(enum.Enum):
    simple = 'simple'
    detailed = 'detailed'
    json = 'json'


@main.command('list')
@click.argument(
    'addons', nargs=-1, callback=_callbackify(partial(parse_into_defn, raise_invalid=False))
)
@click.option(
    '--format',
    '-f',
    'output_format',
    type=EnumParam(ListFormats),
    default=ListFormats.simple.name,
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
            str(d.with_(alias=p.slug) if p else d)
            for d in pkg.deps
            for d in (Defn(pkg.source, d.id),)
            for d, p in ((d, obj.m.get_pkg(d)),)
        )

    def get_wowi_desc_from_toc(pkg: models.Pkg):
        if pkg.source == 'wowi':
            toc_reader = TocReader.from_parent_folder(obj.m.config.addon_dir / pkg.folders[0].name)
            return toc_reader['Notes'].value
        else:
            return pkg.description

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
        )
        .order_by(models.Pkg.source, models.Pkg.name)
        .all()
    )
    if output_format is ListFormats.json:
        click.echo(MultiPkgModel.parse_obj(pkgs).json(indent=2))
    elif output_format is ListFormats.detailed:
        formatter = click.HelpFormatter(max_width=99)
        for pkg in pkgs:
            with formatter.section(Defn.from_pkg(pkg)):
                formatter.write_dl(
                    (
                        ('Name', pkg.name),
                        ('Description', get_wowi_desc_from_toc(pkg)),
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
        click.echo(''.join(f'{Defn.from_pkg(p)}\n' for p in pkgs), nl=False)


@main.command(hidden=True)
@click.argument('addon', callback=_callbackify(partial(parse_into_defn, raise_invalid=False)))
@click.pass_context
def info(ctx: click.Context, addon: Defn) -> None:
    "Alias of `list -f detailed`."
    ctx.invoke(list_installed, addons=(addon,), output_format=ListFormats.detailed)


@main.command()
@click.argument('addon', callback=_callbackify(partial(parse_into_defn, raise_invalid=False)))
@click.pass_obj
def reveal(obj: ManagerWrapper, addon: Defn) -> None:
    "Bring an add-on up in your file manager."
    pkg = obj.m.get_pkg(addon, partial_match=True)
    if pkg:
        click.launch(str(obj.m.config.addon_dir / pkg.folders[0].name), locate=True)
    else:
        Report([(addon, E.PkgNotInstalled())]).generate_and_exit()


def _show_active_config(ctx: click.Context, _param: click.Parameter, value: bool):
    if value:
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
@click.pass_context
def configure(ctx: click.Context) -> Config:
    "Configure instawow."
    from prompt_toolkit.completion import PathCompleter, WordCompleter

    from .prompts import PydanticValidator, text

    addon_dir = text(
        'Add-on directory: ',
        completer=PathCompleter(only_directories=True, expanduser=True),
        validate=PydanticValidator(Config, 'addon_dir'),
    ).unsafe_ask()
    game_flavour = text(
        'Game flavour: ',
        default='classic' if Config.is_classic_folder(addon_dir) else 'retail',
        completer=WordCompleter(['retail', 'classic']),
        validate=PydanticValidator(Config, 'game_flavour'),
    ).unsafe_ask()
    config = Config(
        profile=ctx.find_root().params['profile'], addon_dir=addon_dir, game_flavour=game_flavour
    ).write()
    click.echo(f'Configuration written to: {config.config_file}')
    return config


@main.group('weakauras-companion')
def _weakauras_group():
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
    from textwrap import fill

    from .wa_updater import BuilderConfig, WaCompanionBuilder

    config = BuilderConfig()
    aura_groups = WaCompanionBuilder(obj.m, config).extract_installed_auras()
    installed_auras = sorted(
        (g._filename, fill(a.id, width=30, max_lines=1), a.url)
        for g in aura_groups
        for v in g.__root__.values()
        for a in v
        if not a.parent
    )
    click.echo(tabulate([('in file', 'name', 'URL'), *installed_auras]))


@main.command(hidden=True)
@click.argument('filename', type=PathParam(dir_okay=False))
@click.option(
    '--age-cutoff',
    type=str,
    default=None,
    callback=lambda _, __, v: v and datetime.fromisoformat(v),
)
def generate_catalogue(filename: Path, age_cutoff: O[datetime]) -> None:
    "Generate the master catalogue."
    import asyncio

    from .resolvers import Catalogue

    catalogue = asyncio.run(Catalogue.collate(age_cutoff))
    filename.write_text(catalogue.json(indent=2), encoding='utf-8')
    filename.with_suffix(f'.compact{filename.suffix}').write_text(
        catalogue.json(separators=(',', ':')), encoding='utf-8'
    )


@main.command(hidden=True)
@click.pass_context
def listen(ctx: click.Context) -> None:
    "Fire up the WebSocket server."
    import asyncio

    from . import json_rpc_server

    dummy_config = Config.get_dummy_config(profile='__jsonrpc__').ensure_dirs()
    log_level = ctx.find_root().params['log_level']
    setup_logging(dummy_config, log_level)
    _override_loop_policy()
    asyncio.run(json_rpc_server.listen())
