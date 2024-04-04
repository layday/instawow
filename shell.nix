{ pkgs ? import <nixpkgs> { } }:
let
  python = pkgs.python312;
  venvDir = toString ./venvs + ("/" + python.pythonVersion);
in
pkgs.mkShell {
  buildInputs = [
    pkgs.nixpkgs-fmt
    pkgs.nodejs_20
    pkgs.nil
    pkgs.uv
    python
    python.pkgs.venvShellHook
  ];

  SOURCE_DATE_EPOCH = "315532800"; # The year 1980
  PYTHONBREAKPOINT = "IPython.terminal.debugger.set_trace";

  shellHook = ''
    if [ -d "${venvDir}" ]; then
      echo "Skipping venv creation, '${venvDir}' already exists"
    else
      echo "Creating new venv environment in path: '${venvDir}'"
      # Note that the module venv was only introduced in python 3, so for 2.7
      # this needs to be replaced with a call to virtualenv
      uv venv "${venvDir}"
    fi

    source "${venvDir}/bin/activate"

    AIOHTTP_NO_EXTENSIONS=1 MULTIDICT_NO_EXTENSIONS=1 CC=clang++ uv pip install nox -e ".[gui, test, types]"
  '';
}
