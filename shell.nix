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
    python -m pip uninstall -y setuptools
    python -m pip install -U pip ipython nox frontend-editables
    python -m frontend_editables.transitional_cli \
      --method lax_symlink --spec ".[gui, test, types]" \
      src/instawow instawow \
      gui-webview/src/instawow_gui instawow_gui
  '';
}
