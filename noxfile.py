from __future__ import annotations

import json
import os
import tempfile
from importlib.metadata import Distribution
from pathlib import Path

import nox

nox.needs_version = '>= 2024.4.15'
nox.options.default_venv_backend = 'uv|venv'
nox.options.error_on_external_run = True


_DEPENDENCY_GROUPS = {
    'build': ['build[uv]'],
    'format_or_lint': ['ruff'],
    'publish': ['twine'],
    'report_coverage': ['coverage[toml]'],
}

_ROOT = Path(__file__).parent


def _install_coverage_hook(session: nox.Session):
    session.run(
        'python',
        '-c',
        """\
from pathlib import Path
import sysconfig

(Path(sysconfig.get_path('purelib')) / 'coverage.pth').write_text(
    'import coverage; coverage.process_startup()',
    encoding='utf-8',
)
""",
    )


def _locate_or_build_packages(session: nox.Session):
    wheels_metadata_json = {
        d: _ROOT / 'dist' / d / '.wheel-metadata.json' for d in ['instawow', 'instawow-gui']
    }
    if not all(j.exists() for j in wheels_metadata_json.values()):
        if os.environ.get('CI'):
            raise RuntimeError('Packages are missing')
        build_dists(session)

    return {d: json.loads(p.read_bytes()) for d, p in wheels_metadata_json.items()}


@nox.session(reuse_venv=True)
def dev_env(session: nox.Session):
    "Bootstrap the dev env."

    session.install('-e', '.[test, types]', '-e', './instawow-gui[full]')
    print(session.virtualenv.bin, end='')


@nox.session(name='format')
def format_code(session: nox.Session):
    "Format source code."

    session.install(*_DEPENDENCY_GROUPS['format_or_lint'])

    check = '--check' in session.posargs
    skip_prettier = '--skip-prettier' in session.posargs

    session.run('ruff', 'check', '--select', 'I', *[] if check else ['--fix'], '.')
    session.run('ruff', 'format', *['--check'] if check else [], '.')

    if not skip_prettier:
        with session.chdir('instawow-gui/frontend'):
            session.run('npm', 'install', external=True)
            session.run('npx', 'prettier', '--check' if check else '--write', '.', external=True)


@nox.session
def lint(session: nox.Session):
    "Lint source code."

    session.install(*_DEPENDENCY_GROUPS['format_or_lint'])
    session.run('ruff', 'check', '--output-format', 'full', *session.posargs, '.')
    session.notify('format', ['--check'])


@nox.session
@nox.parametrize('minimum_versions', [False, True], ['latest', 'minimum-versions'])
def test(session: nox.Session, minimum_versions: bool):
    "Run the test suite."

    if minimum_versions and session.venv_backend != 'uv':
        session.error('`minimum_versions` only supported with uv')

    if not os.environ.get('CI'):
        session.create_tmp()

    packages = _locate_or_build_packages(session)

    install_args = [
        f'instawow[test] @ {packages["instawow"]["wheel-path"]}',
        f'instawow-gui[skeletal] @ {packages["instawow-gui"]["wheel-path"]}',
        'instawow_test_plugin @ tests/plugin',
    ]
    if minimum_versions:
        (package_metadata,) = Distribution.discover(
            name='instawow', path=[packages['instawow']['wheel-path']]
        )
        session.install(
            '--resolution',
            'lowest-direct',
            *install_args,
            *(package_metadata.requires or ()),
        )
    else:
        session.install(*install_args)

    _install_coverage_hook(session)

    session.run(
        *'coverage run -m pytest -n auto'.split(),
        env={
            'COVERAGE_PROCESS_START': 'pyproject.toml',
        },
    )


@nox.session
def produce_coverage_report(session: nox.Session):
    "Produce coverage report."

    session.install(*_DEPENDENCY_GROUPS['report_coverage'])
    session.run('coverage', 'combine')
    session.run('coverage', 'html', '--skip-empty')
    session.run('coverage', 'report', '-m')


@nox.session
def type_check(session: nox.Session):
    "Run Pyright."

    packages = _locate_or_build_packages(session)

    session.install(
        f'instawow[test, types] @ {packages["instawow"]["wheel-path"]}',
        f'instawow-gui[skeletal] @ {packages["instawow-gui"]["wheel-path"]}',
    )
    session.run('npx', 'pyright', external=True)


@nox.session(python=False)
def bundle_frontend(session: nox.Session):
    "Bundle the frontend."

    with session.chdir('instawow-gui/frontend'):
        session.run('git', 'clean', '-fX', '../src/instawow_gui/frontend', external=True)
        session.run('npm', 'install', external=True)
        session.run('npx', 'svelte-check', external=True)
        session.run('npm', 'run', 'build', external=True)


@nox.session
def build_dists(session: nox.Session):
    "Build an sdist and wheel."

    session.run('git', 'clean', '-fdX', 'dist', external=True)
    session.install(*_DEPENDENCY_GROUPS['build'])

    for name, source_dir in ('instawow', '.'), ('instawow-gui', 'instawow-gui'):
        if name == 'instawow-gui':
            bundle_frontend(session)

        out_dir = Path('dist', name)
        session.run('pyproject-build', '--installer', 'uv', '--outdir', str(out_dir), source_dir)

        wheel_path = next(f.path for f in os.scandir(out_dir) if f.name.endswith('.whl'))
        (wheel_metadata,) = Distribution.discover(name=name, path=[wheel_path])
        (out_dir / '.wheel-metadata.json').write_text(
            json.dumps(
                {
                    'wheel-path': wheel_path,
                    'version': wheel_metadata.version,
                }
            ),
            encoding='utf-8',
        )


@nox.session
def publish_dists(session: nox.Session):
    "Validate and upload dists to PyPI."

    session.install(*_DEPENDENCY_GROUPS['publish'])
    session.run('twine', 'check', '--strict', 'dist/instawow/*')
    session.run('twine', 'upload', '--verbose', 'dist/instawow/*')


@nox.session(python=False)
def freeze_cli(session: nox.Session):
    "Freeze the CLI with PyApp."

    import argparse
    import shutil

    PYAPP_VERSION = 'v0.22.0'

    parser = argparse.ArgumentParser()
    parser.add_argument('--out-dir', required=True)
    options = parser.parse_args(session.posargs)

    packages = _locate_or_build_packages(session)

    pyapp_configuration = {
        'PYAPP_PROJECT_PATH': os.fspath(Path(packages['instawow']['wheel-path']).absolute()),
        'PYAPP_EXEC_MODULE': 'instawow',
        'PYAPP_FULL_ISOLATION': '1',
        'PYAPP_PYTHON_VERSION': '3.12',
        'PYAPP_DISTRIBUTION_EMBED': '1',
        'PYAPP_PIP_EXTERNAL': '1',
        'PYAPP_PIP_EXTRA_ARGS': '--only-binary :all:',
        'PYAPP_UV_ENABLED': '1',
    }

    with tempfile.TemporaryDirectory() as app_temp_dir:
        session.run(
            'cargo',
            'install',
            '--git',
            'https://github.com/ofek/pyapp',
            '--tag',
            PYAPP_VERSION,
            '--force',
            '--root',
            app_temp_dir,
            external=True,
            env=pyapp_configuration,
        )

        for suffix in '', '.exe':
            from_path = Path(app_temp_dir, 'bin', 'pyapp').with_suffix(suffix)
            if not from_path.exists():
                continue

            to_path = Path(options.out_dir, 'instawow').with_suffix(suffix)
            to_path.parent.mkdir(exist_ok=True, parents=True)
            shutil.copy(from_path, to_path)

            break

        else:
            raise RuntimeError('built executable not found')


@nox.session
def freeze_gui(session: nox.Session):
    "Freeze the GUI with briefcase."

    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', default=sys.platform)
    parser.add_argument('--release', action='store_true')
    options = parser.parse_args(session.posargs)

    packages = _locate_or_build_packages(session)

    spec_path = _ROOT / 'instawow-gui' / 'pyproject.toml'
    spec = spec_path.read_text(encoding='utf-8')
    spec = spec.replace(
        '"instawow-gui[full]"',
        f'"instawow-gui[full] @ {Path(packages["instawow-gui"]["wheel-path"]).resolve().as_uri()}"',
    )
    if options.release:
        (package_metadata,) = Distribution.discover(
            name='instawow-gui', path=[packages['instawow-gui']['wheel-path']]
        )
        spec = spec.replace(
            'version = "0.1.0"',
            f'version = "{package_metadata.version}"',
        )
    spec_path.write_text(spec, encoding='utf-8')

    if options.platform == 'linux':
        build_opts = package_opts = ['linux', 'flatpak']
    elif options.platform == 'darwin':
        build_opts = []
        package_opts = ['--adhoc-sign']
    else:
        build_opts = []
        package_opts = []

    session.install('briefcase')

    with session.chdir('instawow-gui'):
        session.run('briefcase', 'build', *build_opts)
        session.run('briefcase', 'package', *package_opts)
