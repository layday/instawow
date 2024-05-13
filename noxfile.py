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


def _session_install_for_python_next(session: nox.Session, install_args: list[str]):
    is_python_next = session.run(
        'python', '-c', 'import sys; print(int(sys.version_info >= (3, 13)), end=" ")', silent=True
    )
    if is_python_next == '1':
        with tempfile.TemporaryDirectory() as temp_dir:
            constraints_txt = Path(temp_dir, 'python-next-constraints.txt')
            constraints_txt.write_text("""\
typing-extensions @ git+https://github.com/python/typing_extensions
    """)

            session.install('-c', os.fspath(constraints_txt), *install_args)
    else:
        session.install(*install_args)


@nox.session(reuse_venv=True)
def dev_env(session: nox.Session):
    "Bootstrap the dev env."

    _session_install_for_python_next(session, ['-e', '.[gui, test, types]'])
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

    if session.posargs:
        (package_path,) = session.posargs
    else:
        build_dists(session)

        with Path('dist', '.wheel-metadata.json').open('rb') as wheel_metadata_json:
            package_path = json.load(
                wheel_metadata_json,
            )['wheel-path']

    install_args = [
        f'instawow[skeletal-gui, test] @ {package_path}',
        'instawow_test_plugin @ tests/plugin',
    ]
    if minimum_versions:
        (package_metadata,) = Distribution.discover(name='instawow', path=[package_path])
        _session_install_for_python_next(
            session,
            [
                '--resolution',
                'lowest-direct',
                *install_args,
                *(package_metadata.requires or ()),
            ],
        )
    else:
        _session_install_for_python_next(session, install_args)

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

    if session.posargs:
        (package_path,) = session.posargs
    else:
        build_dists(session)

        with Path('dist', '.wheel-metadata.json').open('rb') as wheel_metadata_json:
            package_path = json.load(
                wheel_metadata_json,
            )['wheel-path']

    _session_install_for_python_next(
        session,
        [f'instawow[skeletal-gui, types] @ {package_path}'],
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
    session.run('pyproject-build', '--installer', 'uv')

    wheel_path = next(f.path for f in os.scandir('dist') if f.name.endswith('.whl'))
    (wheel_metadata,) = Distribution.discover(name='instawow', path=[wheel_path])

    Path('dist', '.wheel-metadata.json').write_text(
        json.dumps(
            {
                'wheel-path': wheel_path,
                'wheel-version': wheel_metadata.version,
            }
        ),
        encoding='utf-8',
    )


@nox.session
def publish_dists(session: nox.Session):
    "Validate and upload dists to PyPI."

    session.install(*_DEPENDENCY_GROUPS['publish'])
    session.run('twine', 'check', '--strict', 'dist/*')
    session.run('twine', 'upload', '--verbose', 'dist/*')


@nox.session(python=False)
def freeze_cli(session: nox.Session):
    "Freeze the CLI with PyApp."

    import argparse
    import shutil

    PYAPP_VERSION = 'v0.20.0'

    parser = argparse.ArgumentParser()
    parser.add_argument('--wheel-file', required=True)
    parser.add_argument('--out-dir', required=True)

    options = parser.parse_args(session.posargs)

    pyapp_configuration = {
        'PYAPP_PROJECT_PATH': os.fspath(Path(options.wheel_file).absolute()),
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

            print(to_path, end='')
            break

        else:
            raise RuntimeError('built executable not found')


@nox.session(python=False)
def patch_frontend_spec(session: nox.Session):
    "Patch the wheel path and version in the frontend spec."

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--version')
    parser.add_argument('--wheel-file')

    options = parser.parse_args(session.posargs)

    spec_path = Path(__file__).parent.joinpath('instawow-gui', 'pyproject.toml')
    spec = spec_path.read_text(encoding='utf-8')

    if options.version:
        spec = spec.replace('version = "0.1.0"', f'version = "{options.version}"')

    if options.wheel_file:
        spec = spec.replace(
            '"instawow[gui]"', f'"instawow[gui] @ {Path(options.wheel_file).resolve().as_uri()}"'
        )

    spec_path.write_text(spec, encoding='utf-8')
