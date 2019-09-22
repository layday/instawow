with import <nixpkgs> {};

let
  venvDir = ".venv";
in mkShell {
  buildInputs = [
    ctags
    python37
  ];

  shellHook = ''
    [[ -d ${venvDir} ]] || python3.7 -m venv ${venvDir}
    export PATH="$(pwd)/${venvDir}/bin:$PATH"
    unset SOURCE_DATE_EPOCH

    export PYTHONBREAKPOINT="IPython.terminal.debugger.set_trace"
    export INSTAWOW_DEV=1
  '';
}
