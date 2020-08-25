import os

import nox

nox.options.envdir = '.py-nox'


@nox.session(python=['3.7', '3.8'])
def test(session):
    session.install('.[server,test]')
    session.run('coverage', 'run', '-m', 'pytest')
    session.run('coverage', 'report', '-m')


@nox.session(python=False)
def update_typeshed(session):
    types_dir = '.py-types'

    session.run('rm', '-rf', types_dir)
    session.run(
        *f'git clone --depth 1 https://github.com/python/typeshed {types_dir}/typeshed'.split()
    )


@nox.session(python=['3.7', '3.8'])
def type_check(session):
    session.install('.[server,test]')
    session.run('npx', '--cache', '.npm', 'pyright', '--lib')


@nox.session(python='3.7', reuse_venv=True)
def reformat(session):
    session.install('isort>=5.0.7', 'black>=19.10b0')
    for cmd in 'isort', 'black':
        session.run(cmd, 'instawow', 'tests', 'noxfile.py', 'setup.py')


@nox.session(python=False)
def clobber_build_artefacts(session):
    session.run('rm', '-rf', 'build', 'dist', 'instawow.egg-info')


@nox.session(python='3.7')
def build(session):
    clobber_build_artefacts(session)
    session.install('pep517')
    session.run('python', '-m', 'pep517.build', '.')


@nox.session(python='3.7')
def publish(session):
    session.install('twine')
    session.run('twine', 'upload', 'dist/*')


@nox.session
def nixify(session):
    nixify_dir = os.environ.get('INSTAWOW_NIXIFY_DIR', '.')

    session.cd(nixify_dir)
    # The latest published version of pypi2nix (2.0.4) overrides the pip
    # derivation's fetch URL with an old version of pip from GitHub which cannot
    # be built with an up-to-date derivation because the latter attempts
    # to apply a patch to a file which does not exist in the pip of olde
    session.install('pypi2nix @ https://github.com/nix-community/pypi2nix/archive/0dbd11.zip')
    session.run('pypi2nix', '-vvv', '-e', 'instawow')
