from __future__ import annotations

import json
import os
from importlib.metadata import Distribution
from pathlib import Path

import nox

nox.options.default_venv_backend  = 'uv'  # fmt: skip
nox.options.error_on_external_run = True


def install_coverage_hook(session: nox.Session):
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


@nox.session(name='format')
def format_code(session: nox.Session):
    "Format source code."

    session.install('ruff')

    check = '--check' in session.posargs

    session.run('ruff', 'check', '--select', 'I', *[] if check else ['--fix'], '.')
    session.run('ruff', 'format', *['--check'] if check else [], '.')

    if '--skip-prettier' not in session.posargs:
        with session.chdir('instawow-gui/frontend'):
            session.run('npm', 'install', external=True)
            session.run('npx', 'prettier', '--check' if check else '--write', '.', external=True)


@nox.session
def lint(session: nox.Session):
    "Lint source code."
    session.install('ruff')
    session.run('ruff', 'check', '--output-format', 'full', *session.posargs, '.')
    session.notify('format', ['--check'])


@nox.session
@nox.parametrize('minimum_versions', [False, True], ['latest', 'minimum-versions'])
def test(session: nox.Session, minimum_versions: bool):
    "Run the test suite."

    if not os.environ.get('CI'):
        session.create_tmp()

    if session.posargs:
        (package_path,) = session.posargs
    else:
        build_dists(session)

        with Path('dist', 'wheel-metadata.json').open('rb') as wheel_metadata_json:
            package_path = json.load(
                wheel_metadata_json,
            )['wheel-path']

    install_requires = [
        f'instawow[gui, test] @ {package_path}',
        'instawow_test_plugin @ tests/plugin',
    ]

    if minimum_versions:
        (package_metadata,) = Distribution.discover(name='instawow', path=[package_path])

        session.install(
            '--resolution', 'lowest-direct', *install_requires, *package_metadata.requires or ()
        )
    else:
        session.install(*install_requires)

    install_coverage_hook(session)

    session.run(
        *'coverage run -m pytest -n auto'.split(),
        env={
            'COVERAGE_PROCESS_START': 'pyproject.toml',
        },
    )


@nox.session
def produce_coverage_report(session: nox.Session):
    "Produce coverage report."
    session.install('coverage[toml]')
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

        with Path('dist', 'wheel-metadata.json').open('rb') as wheel_metadata_json:
            package_path = json.load(
                wheel_metadata_json,
            )['wheel-path']

    session.install(f'instawow[gui] @ {package_path}')
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
    session.install(
        'build',
        'pip',  # To avoid having to run ensurepip.
    )
    session.run('pyproject-build')

    wheel_path = next(f.path for f in os.scandir('dist') if f.name.endswith('.whl'))
    (wheel_metadata,) = Distribution.discover(name='instawow', path=[wheel_path])

    Path('dist', 'wheel-metadata.json').write_text(
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
    session.install('twine')
    session.run('twine', 'check', '--strict', 'dist/*')
    session.run('twine', 'upload', '--verbose', 'dist/*')


@nox.session(python=False)
def freeze_cli(session: nox.Session):
    import argparse
    import shutil
    import tempfile

    PYAPP_VERSION = 'v0.15.1'

    parser = argparse.ArgumentParser()
    parser.add_argument('--wheel-file', required=True)
    parser.add_argument('--out-dir', required=True)

    options = parser.parse_args(session.posargs)

    pyapp_configuration = {
        'PYAPP_PROJECT_PATH': os.fspath(Path(options.wheel_file).absolute()),
        'PYAPP_EXEC_MODULE': 'instawow',
        'PYAPP_PYTHON_VERSION': '3.11',
        'PYAPP_DISTRIBUTION_EMBED': '1',
        'PYAPP_PIP_EXTERNAL': '1',
        'PYAPP_PIP_EXTRA_ARGS': '--only-binary :all:',
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

        for suffix in ['', '.exe']:
            from_path = Path(app_temp_dir, 'bin', 'pyapp').with_suffix(suffix)
            if not from_path.exists():
                continue

            to_path = Path(options.out_dir, 'instawow').with_suffix(suffix)
            to_path.parent.mkdir(parents=True)
            shutil.copy(from_path, to_path)

            print(to_path, end='')
            break


@nox.session(python=False)
def patch_frontend_spec(session: nox.Session):
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
