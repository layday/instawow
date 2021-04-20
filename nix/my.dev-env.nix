{ pkgs ? import <nixpkgs> { } }:
let
  python = pkgs.python39;
in
pkgs.mkShell {
  buildInputs = [
    python
    python.pkgs.venvShellHook
    pkgs.nodejs-15_x
  ];

  venvDir = toString ./../venvs + ("/" + python.pythonVersion);

  VIRTUAL_ENV_DISABLE_PROMPT = "1";
  SOURCE_DATE_EPOCH = "315532800"; # The year 1980
  PYTHONBREAKPOINT = "IPython.terminal.debugger.set_trace";

  postVenvCreation = ''
    python -m pip install -U pip
    python -m pip install nox
    nox -s build_editable
    python -m pip install "$(find dist -name 'instawow-*.whl')[server, test, types]"
  '';
}
