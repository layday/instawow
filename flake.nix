{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python314;
      in
      {
        devShells.default = pkgs.mkShell {
          nativeBuildInputs = [
            pkgs.uv
            python
            (python.pkgs.nox.overridePythonAttrs (old: {
              # Propagating dependencies leaks them through $PYTHONPATH which causes issues
              # when used in nix-shell.
              postFixup = ''
                rm $out/nix-support/propagated-build-inputs
              '';
            }))
          ];

          SOURCE_DATE_EPOCH = "315532800"; # The year 1980
          PYTHONBREAKPOINT = "IPython.terminal.debugger.set_trace";
          UV_NO_MANAGED_PYTHON = "1";

          shellHook = ''
            set -ex

            VENV_BIN_DIR=$(nox -vv -s dev_env --force-python ${python.pythonVersion})
            source "$VENV_BIN_DIR/activate"
          '';
        };
      }
    );
}
