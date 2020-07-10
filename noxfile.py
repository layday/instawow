import os
import subprocess as sp

import nox

nox.options.envdir = '.py-nox'


@nox.session(python=['3.7', '3.8'])
def test(session):
    session.install('.[test]')
    session.run('coverage', 'run', '-m', 'pytest', '-o', 'xfail_strict=true', 'tests')
    session.run('coverage', 'report', '-m')


@nox.session(python=['3.7', '3.8'])
def type_check(session):
    session.install('.')
    session.run('npx', '--cache', '.npm', 'pyright', '--lib')


@nox.session(python='3.7')
def reformat(session):
    session.install('isort>=5.0.7', 'black>=19.10b0')
    session.run('isort', 'instawow', 'tests', 'noxfile.py', 'setup.py')
    session.run('black', 'instawow', 'tests', 'noxfile.py', 'setup.py')


@nox.session(python=False)
def update_stubs(session):
    sp.run(
        """\
        types_dir=.py-types
        rm -rf $types_dir && mkdir $types_dir && cd $types_dir && {
          git clone --depth 1 \
            https://github.com/python/typeshed
          git clone --depth 1 \
            https://github.com/dropbox/sqlalchemy-stubs stubs/_sqlalchemy-stubs
          cp -r stubs/_sqlalchemy-stubs/sqlalchemy-stubs stubs/sqlalchemy
        }
    """,
        shell=True,
        executable='bash',
    )


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
    session.cd(os.environ.get('INSTAWOW_NIXIFY_DIR', '.'))
    session.install('pypi2nix')
    session.run('pypi2nix', '-e', 'instawow')
