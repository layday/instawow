from __future__ import annotations

import io
from pathlib import Path
import posixpath
from textwrap import dedent
from urllib.request import urlopen
from zipfile import ZipFile

import nox

nox.options.sessions = ['format', 'test', 'type_check']

WEBVIEW2_VERSION = '1.0.1054.31'


def mirror_repo(session: nox.Session):
    repo_dir = f'{session.create_tmp()}/instawow'
    session.run('git', 'clone', '.', repo_dir, external=True)
    session.chdir(repo_dir)


def install_coverage_hook(session: nox.Session):
    session.run(
        'python',
        '-c',
        '''\
from pathlib import Path
import sysconfig

(Path(sysconfig.get_path('purelib')) / 'coverage.pth').write_text(
    'import coverage; coverage.process_startup()',
    encoding='utf-8',
)
''',
    )


@nox.session(name='format', reuse_venv=True)
def format_(session: nox.Session):
    "Format source code."
    session.install('isort', 'black')

    check = '--check' in session.posargs
    for cmd in ['isort', 'black']:
        session.run(
            cmd, *['--check'] if check else [], 'src', 'gui-webview/src', 'tests', 'noxfile.py'
        )

    if '--skip-prettier' not in session.posargs:
        session.chdir('gui-webview/frontend')
        session.run(
            'npx',
            'prettier',
            '--check' if check else '--write',
            'src',
            'package.json',
            'rollup.config.js',
            'tsconfig.json',
            external=True,
        )


@nox.session(python='3.9')
@nox.parametrize(
    'constraints',
    [
        '',
        dedent(
            '''\
            aiohttp == 3.7.4
            alembic == 1.7.0
            click == 8.0.0
            jinja2 == 3.0.0
            loguru == 0.5.3
            pluggy == 0.13.0
            prompt-toolkit == 3.0.15
            pydantic == 1.9.0
            questionary == 1.10.0
            rapidfuzz == 1.4.1
            sqlalchemy == 1.4.23
            typing-extensions == 4.0.0
            yarl == 1.6.3
            aiohttp-rpc == 1.0.0
            '''
        ),
    ],
    [
        'latest',
        'minimum-versions',
    ],
)
def test(session: nox.Session, constraints: str):
    "Run the test suite."
    mirror_repo(session)

    constraints_txt = 'constraints.txt'
    Path(constraints_txt).write_text(constraints)

    session.install('-c', constraints_txt, '.[gui, test]', './tests/plugin')
    install_coverage_hook(session)

    session.run(
        *'coverage run -m pytest -n auto'.split(),
        env={'COVERAGE_PROCESS_START': 'pyproject.toml'},
    )
    session.run('coverage', 'combine')
    session.run('coverage', 'report', '-m')
    session.run('coverage', 'xml')


@nox.session(python='3.9')
def type_check(session: nox.Session):
    "Run Pyright."
    mirror_repo(session)
    session.install('.[gui, types]')
    session.run('npx', 'pyright', external=True)


@nox.session(python=False)
def bundle_frontend(session: nox.Session):
    "Bundle the frontend."
    session.run('git', 'clean', '-fX', 'gui-webview/src/instawow_gui/frontend', external=True)
    session.chdir('gui-webview/frontend')
    session.run('npm', 'install', external=True)
    session.run('npx', 'rollup', '-c', external=True)


@nox.session(python=False)
def bundle_webview2_libs(session: nox.Session):
    with urlopen(
        f'https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/{WEBVIEW2_VERSION}'
    ) as response:
        with ZipFile(io.BytesIO(response.read())) as nupkg:
            for file_path in [
                'LICENSE.txt',
                'lib/net45/Microsoft.Web.WebView2.Core.dll',
                'lib/net45/Microsoft.Web.WebView2.WinForms.dll',
                'runtimes/win-x64/native/WebView2Loader.dll',
            ]:
                with nupkg.open(file_path) as file_in, Path(
                    'gui-webview/src/instawow_gui/webview2', posixpath.basename(file_path)
                ).open('wb') as file_out:
                    file_out.write(file_in.read())


@nox.session
def build_dists(session: nox.Session):
    "Build an sdist and wheel."
    session.run('git', 'clean', '-fdX', 'dist', external=True)
    session.install(
        'build',
        'poetry-core @ git+https://github.com/layday/poetry-core@fix-multi-package-srcs',
        'poetry-dynamic-versioning',
    )
    session.run('python', '-m', 'build', '-n')


@nox.session
def publish_dists(session: nox.Session):
    "Validate and upload dists to PyPI."
    session.install('twine')
    session.run('twine', 'check', '--strict', 'dist/*')
    session.run('twine', 'upload', 'dist/*')


@nox.session
def freeze_cli(session: nox.Session):
    session.install(
        'pyinstaller',
        '.',
        'certifi',
    )
    main_py = session.run(
        'python',
        '-c',
        'import instawow.__main__; print(instawow.__main__.__file__, end="")',
        silent=True,
    )
    assert main_py
    session.run(
        'pyinstaller',
        '--clean',
        '-y',
        '--onedir',
        '-n',
        'instawow-standalone',
        '--collect-all',
        'instawow',
        '--exclude-module',
        'instawow_gui',
        '--console',
        main_py,
    )
    session.run('git', 'clean', '-fX', 'instawow-standalone.spec', external=True)
