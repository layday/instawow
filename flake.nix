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
      in
      {
        devShells.default = pkgs.mkShell (
          let
            devPython = pkgs.python315;
          in
          {
            nativeBuildInputs = [
              pkgs.uv
              devPython
              (pkgs.python314.pkgs.nox.overridePythonAttrs (old: {
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

              VENV_BIN_DIR=$(nox -vv -s dev_env --force-python ${devPython.pythonVersion})
              source "$VENV_BIN_DIR/activate"
            '';
          }
        );

        packages = {
          instawow =
            pkgs.callPackage
              (
                {
                  plugins ? [ ],
                }:
                pkgs.python3Packages.buildPythonPackage (finalAttrs: {
                  name = "instawow";
                  # version = "";
                  pyproject = true;

                  src = pkgs.lib.cleanSource ./.;

                  nativeBuildInputs = with pkgs.python3Packages; [
                    hatchling
                    versioningit
                  ];
                  propagatedBuildInputs =
                    with pkgs.python3Packages;
                    [
                      aiohttp
                      aiohttp-client-cache
                      attrs
                      cattrs
                      click
                      diskcache
                      loguru
                      packaging
                      pluggy
                      prompt-toolkit
                      rapidfuzz
                      truststore
                      typing-extensions
                      wcwidth
                      yarl
                    ]
                    ++ plugins;
                })
              )
              {
                plugins = [ ];
              };
        };
      }
    );
}
