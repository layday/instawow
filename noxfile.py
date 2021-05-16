from __future__ import annotations

import nox

SUPPORTED_PYTHON_VERSIONS = ['3.7', '3.8', '3.9']


def _mirror_project(session: nox.Session):
    tmp_dir = session.create_tmp()
    session.run('git', 'clone', '.', tmp_dir, external=True)
    session.chdir(tmp_dir)


@nox.session(reuse_venv=True)
def reformat(session: nox.Session):
    "Reformat Python source code using Black and JavaScript using Prettier."
    session.install('isort >=5.8.0', 'black >=20.8b1')
    for cmd in ('isort', 'black'):
        session.run(cmd, 'instawow', 'tests', 'noxfile.py')

    if '--skip-prettier' not in session.posargs:
        session.chdir('gui')
        session.run(
            'npx',
            'prettier',
            '--write',
            'src',
            'package.json',
            'rollup.config.js',
            'tsconfig.json',
            external=True,
        )


@nox.session(python=SUPPORTED_PYTHON_VERSIONS)
@nox.parametrize(
    'constraints',
    [
        '',
        '''\
aiohttp ==3.7.4
alembic ==1.4.3
click ==7.1
jellyfish ==0.8.2
jinja2 ==2.11.0
loguru ==0.1.0
pluggy ==0.13.0
prompt-toolkit ==3.0.15
pydantic ==1.8.0
questionary ==1.8.0
sqlalchemy ==1.3.19
typing-extensions ==3.10.0.0
yarl ==1.4
''',
    ],
    [
        'none',
        'minimum-versions',
    ],
)
def test(session: nox.Session, constraints: str):
    "Run the test suite."
    _mirror_project(session)

    constraints_txt = 'constraints.txt'
    with open(constraints_txt, 'w') as file:
        file.write(constraints)

    session.install('-c', constraints_txt, '.[server, test]', './tests/plugin')
    session.run('pytest', '--cov', '--cov-report=', '-n', 'auto')
    session.run('coverage', 'report', '-m')


@nox.session(python=SUPPORTED_PYTHON_VERSIONS)
def type_check(session: nox.Session):
    "Run Pyright."
    _mirror_project(session)
    session.install(
        '.[server]',
        'sqlalchemy-stubs@ https://github.com/layday/sqlalchemy-stubs/archive/develop.zip',
    )
    session.run('npx', 'pyright', external=True)


@nox.session(python=False)
def clobber_build_artefacts(session: nox.Session):
    "Remove build artefacts."
    session.run('rm', '-rf', 'dist', external=True)


@nox.session
def bump_version(session: nox.Session):
    "Bump the version of instawow."
    session.install('dunamai')
    session.run(
        'python',
        '-c',
        '''
from pathlib import Path

import dunamai

Path('instawow', '__init__.py').write_text(
    f"""\
from . import _import_wrapper

__getattr__ = _import_wrapper.__getattr__

__version__ = '{dunamai.Version.from_git().serialize(dirty=True)}'
""",
    encoding='utf-8',
)
''',
    )


@nox.session
def build(session: nox.Session):
    "Build an sdist and wheel."
    clobber_build_artefacts(session)
    bump_version(session)
    session.install('build')
    session.run('python', '-m', 'build', '.')


@nox.session
def build_editable(session: nox.Session):
    "Create an editable wheel for development."
    clobber_build_artefacts(session)
    bump_version(session)
    session.install('build')
    editable_flit = f'{session.create_tmp()}/flit'
    session.run('git', 'clone', 'https://github.com/layday/flit', editable_flit, external=True)
    session.run('git', '-C', editable_flit, 'checkout', 'feat-editables', external=True)
    session.run('python', '-m', 'build', '-o', 'dist', '-w', f'{editable_flit}/flit_core')
    session.run(
        *('python', '-m', 'build', '-w', '.'),
        env={'FLIT_EDITABLE': '1', 'PIP_FIND_LINKS': 'dist'},
    )


@nox.session
def build_and_publish(session: nox.Session):
    "Build, validate and upload dists to PyPI."
    build(session)
    session.install('twine')
    for subcmd in ('check', 'upload'):
        session.run('twine', subcmd, 'dist/*')
