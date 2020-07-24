import nox

nox.options.envdir = '.py-nox'
nox.options.reuse_existing_virtualenvs = True


@nox.session(python=['3.7', '3.8'])
def test(session):
    session.install('.[test]')
    session.run('coverage', 'run', '-m', 'pytest', '-o', 'xfail_strict=true', 'tests')
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
    session.install('.[test]')
    session.run('npx', '--cache', '.npm', 'pyright', '--lib')


@nox.session(python='3.7')
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
    import os

    nixify_dir = os.environ.get('INSTAWOW_NIXIFY_DIR', '.')
    session.cd(nixify_dir)
    session.install('pypi2nix')
    session.run('pypi2nix', '-e', 'instawow')
