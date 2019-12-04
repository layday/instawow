import nox


@nox.session(python='3.7')
def bump_dependencies(session):
    session.install('pip-tools')
    session.run('rm', '-f', 'requirements.txt')
    session.run('pip-compile', 'requirements.in')


@nox.session
def test(session):
    session.install('-r', 'requirements-test.txt')
    session.install('.')
    session.run('pytest', *session.posargs)


@nox.session(python='3.7')
def check(session):
    session.install('pep517')
    session.run(*'python3 -m pep517.check .'.split(), *session.posargs)


@nox.session(python='3.7')
def build(session):
    session.install('pep517')
    session.run(*'rm -rf build dist'.split())
    session.run(*'python3 -m pep517.build .'.split(), *session.posargs)


@nox.session(python='3.7')
def publish(session):
    session.install('twine')
    session.run('twine', 'upload', 'dist/*')


@nox.session
def nixify(session):
    location, = session.posargs

    session.install('pypi2nix')
    session.cd(location)
    session.run('rm', '-f', 'requirements.nix',
                            'requirements_overrides.nix',
                            'requirements_frozen.txt')
    session.run('pypi2nix', '-e', 'instawow')


@nox.session
def oxidise(session):
    raise NotImplementedError
