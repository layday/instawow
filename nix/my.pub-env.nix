{ myPythonStr, pkgs ? import <nixpkgs> {} }:

with pkgs;
let
  myPython = lib.getAttrFromPath [ myPythonStr ] pkgs;

  nox = (
    with myPython.pkgs; buildPythonPackage rec {
      pname = "nox";
      version = "2019.11.9";

      doCheck = false;

      propagatedBuildInputs = [ argcomplete colorlog py setuptools virtualenv ];

      src = fetchPypi {
        inherit pname version;
        sha256 = "1f18snv47wp99pzwpiaf2d1vz79mhj5qsg949bx7abdxs9dg9l12";
      };
    }
  );
in
mkShell {
  buildInputs = [
    pkgconfig
    libyaml
    git
    cacert
    myPython
    nox
  ];

  SOURCE_DATE_EPOCH = "315532800"; # The year 1980
}
