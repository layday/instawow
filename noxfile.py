import os

import nox

nox.options.envdir = '.py-nox'
types_dir = '.py-types'


@nox.session(python=False, name='update-stubs')
def update_stubs(session):
    session.run('rm', '-rf', types_dir)
    session.run('mkdir', types_dir)
    session.cd(types_dir)
    session.run('git', 'clone', '--depth', '1', 'https://github.com/python/typeshed')
    session.run('git', 'clone', '--depth', '1', 'https://github.com/dropbox/sqlalchemy-stubs', 'stubs/_sqlalchemy-stubs')
    session.run('cp', '-r', 'stubs/_sqlalchemy-stubs/sqlalchemy-stubs', 'stubs/sqlalchemy')


@nox.session(name='type-check')
def type_check(session):
    session.install('.')
    session.run('npx', '--cache', '.npm', 'pyright', '--lib')


@nox.session(python='3.7')
def reformat(session):
    session.install('isort[pyproject]')
    session.run('isort', '--recursive', 'instawow', 'tests')


@nox.session
def test(session):
    session.install('coverage[toml]',
                    'pytest',
                    'pytest-asyncio',
                    'https://github.com/layday/aresponses/archive/make-responses-reusable.zip',
                    '.')
    session.run('coverage', 'run', '-m', 'pytest', '-o', 'xfail_strict=true', 'tests')
    session.run('coverage', 'report', '-m')


@nox.session(python='3.7', name='bump-dependencies')
def bump_dependencies(session):
    session.install('pip-tools')
    session.run('pip-compile', '-U', '--build-isolation', 'setup.py')


@nox.session(python=False, name='clobber-build-artefacts')
def clobber_build_artefacts(session):
    session.run('rm', '-rf', 'build', 'dist', 'instawow.egg-info')


@nox.session(python='3.7')
def build(session):
    clobber_build_artefacts(session)
    session.install('pep517')
    session.run('python3', '-m', 'pep517.build', '.', *session.posargs)


@nox.session(python='3.7')
def publish(session):
    session.install('twine')
    session.run('twine', 'upload', 'dist/*')


@nox.session
def nixify(session):
    session.cd(os.environ.get('INSTAWOW_NIXIFY_DIR', '.'))
    session.install('pypi2nix')
    session.run('rm', '-f',
                'requirements.nix',
                'requirements_overrides.nix',
                'requirements_frozen.txt')
    session.run('pypi2nix', '-e', 'instawow')
