{ stdenv, writeScriptBin }:

writeScriptBin "nox" ''
  #!${stdenv.shell}

  command="nox $@"
  nix-shell ${./my.pub-env.nix} --argstr myPythonStr python37 --pure --run "$command"
''
