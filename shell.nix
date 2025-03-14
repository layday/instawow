{ pkgs ? import <nixpkgs> { } }:
let
  python = pkgs.python313;
in
pkgs.mkShell {
  buildInputs = [
    pkgs.nil
    pkgs.nixpkgs-fmt
    pkgs.nodejs
    pkgs.python312.pkgs.nox
    pkgs.uv
    python
  ];

  SOURCE_DATE_EPOCH = "315532800"; # The year 1980
  PYTHONBREAKPOINT = "IPython.terminal.debugger.set_trace";

  shellHook = ''
    set -ex

    VENV_BIN_DIR=$(nox -vv -s dev_env --force-python ${python.pythonVersion})
    source "$VENV_BIN_DIR/activate"
  '';
}
