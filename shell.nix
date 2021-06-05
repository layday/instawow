{ pkgs ? import <nixpkgs> { } }:
let
  python = pkgs.python39;
in
pkgs.mkShell {
  buildInputs = [
    python
    python.pkgs.venvShellHook
    pkgs.nodejs-16_x
  ];

  venvDir = toString ./venvs + ("/" + python.pythonVersion);

  VIRTUAL_ENV_DISABLE_PROMPT = "1";
  SOURCE_DATE_EPOCH = "315532800"; # The year 1980
  PYTHONBREAKPOINT = "IPython.terminal.debugger.set_trace";

  postVenvCreation = ''
    python -m pip install -U pip setuptools
    python -m pip install -U ipython nox '.[gui, test, types]'
  '';
}
