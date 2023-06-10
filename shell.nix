{ pkgs ? import <nixpkgs> { } }:
let
  python = pkgs.python311;
  venvDir = toString ./venvs + ("/" + python.pythonVersion);
in
pkgs.mkShell {
  buildInputs = [
    pkgs.nixpkgs-fmt
    pkgs.nodejs_20
    pkgs.rnix-lsp
    python
    python.pkgs.venvShellHook
  ];

  NOX_ENVDIR = venvDir + "/.nox";
  VIRTUAL_ENV_DISABLE_PROMPT = "1";
  SOURCE_DATE_EPOCH = "315532800"; # The year 1980
  PYTHONBREAKPOINT = "IPython.terminal.debugger.set_trace";
  PIP_ONLY_BINARY = ":all:";

  inherit venvDir;

  postVenvCreation = ''
    python -m pip install -U pip ipython nox
    python -m pip uninstall -y setuptools
    python -m pip install -e ".[gui, test, types]"
  '';
}
