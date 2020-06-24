{ myPythonStr
, withRust ? false
, pkgs ? import <nixpkgs> { overlays = [ (import ./my.framework-overlay.nix) ]; }
}:

let
  myPython = pkgs.${myPythonStr};

  pythonVenvDir = toString ./../.py-venvs + ("/" + myPython.pythonVersion);
  cargoHome = toString ./../.cargo;
in
  with pkgs; mkShell {
    buildInputs = [
      pkgconfig
      libiconv
      openssl
      ctags
      myPython
      nodejs-13_x
    ] ++ stdenv.lib.optional withRust [
      rustc
      cargo
      ncurses
    ] ++ stdenv.lib.optional (withRust && stdenv.isDarwin) (
      with darwin.apple_sdk.frameworks; [
        AppKit
        ApplicationServices
        Carbon
        CoreFoundation
        CoreGraphics
        CoreServices
        IOKit
        SystemConfiguration
        Tcl
        Tk # Using overlay!
        Security
      ]
    );

    SOURCE_DATE_EPOCH = "315532800"; # The year 1980
    PYTHONBREAKPOINT = "IPython.terminal.debugger.set_trace";

    CARGO_HOME = cargoHome;
    RUST_BACKTRACE = 1;

    shellHook = ''
      test -d "${pythonVenvDir}" || {
        ${myPython.executable} -m venv "${pythonVenvDir}"
        "${pythonVenvDir}/bin/${myPython.executable}" -m pip install -U pip setuptools
      }
      export PATH="${lib.makeBinPath [ pythonVenvDir cargoHome ]}:$PATH"
    '';
  }
