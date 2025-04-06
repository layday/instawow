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
            pkgs.nil
            pkgs.nixd
            pkgs.nixfmt-rfc-style
            pkgs.nodejs
            pkgs.uv
            python
          ];

          SOURCE_DATE_EPOCH = "315532800"; # The year 1980
          PYTHONBREAKPOINT = "IPython.terminal.debugger.set_trace";

          shellHook = ''
            set -ex

            VENV_BIN_DIR=$(uvx nox -vv -s dev_env --force-python ${python.pythonVersion})
            source "$VENV_BIN_DIR/activate"
          '';
        };
      }
    );
}
