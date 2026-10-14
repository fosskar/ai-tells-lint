{
  lib,
  pkgs,
  runCommand,
  treefmt-nix,
  treefmtModule,
}:
let
  evalWith =
    programConfig:
    (treefmt-nix.lib.evalModule pkgs {
      imports = [ treefmtModule ];
      projectRootFile = "flake.nix";
      programs.ai-tells-lint = programConfig;
    }).config.settings.formatter.ai-tells-lint;

  plain = evalWith { enable = true; };

  configured = evalWith {
    enable = true;
    includes = [ "*.md" ];
    excludes = [ "vendor/*" ];
    settings = {
      ignore = [ "em-dash" ];
      allow.ai-vocabulary = [ "pivotal" ];
      rule = [
        {
          id = "synergy";
          message = "buzzword";
          words = [ "synergy" ];
        }
      ];
    };
  };
in
assert lib.assertMsg (
  plain.includes == [
    "*.md"
    "*.nix"
    "*.sh"
    "*.py"
    "*.go"
    "*.rs"
    "*.c"
    "*.h"
    "*.java"
    "*.js"
    "*.jsx"
    "*.mjs"
    "*.cjs"
    "*.ts"
    "*.tsx"
    "*.mts"
    "*.cts"
    "*.yaml"
    "*.yml"
    "*.toml"
  ]
) "default includes";
assert lib.assertMsg (plain.excludes == [ ]) "default excludes";
assert lib.assertMsg (plain.options == [ ]) "empty settings pass no --config";
assert lib.assertMsg (configured.includes == [ "*.md" ]) "includes";
assert lib.assertMsg (configured.excludes == [ "vendor/*" ]) "excludes";
assert lib.assertMsg (lib.head configured.options == "--config") "settings pass --config";
runCommand "ai-tells-lint-treefmt-module" { } ''
  printf 'a pivotal \342\200\224 synergy\n' >a.md

  status=0
  ${plain.command} ${lib.escapeShellArgs plain.options} a.md >plain.out || status=$?
  [ "$status" -eq 1 ]
  grep -q ': em-dash: ' plain.out
  grep -q ': ai-vocabulary: ' plain.out

  status=0
  ${configured.command} ${lib.escapeShellArgs configured.options} a.md >configured.out || status=$?
  [ "$status" -eq 1 ]
  [ "$(cut -d: -f4 configured.out)" = " synergy" ]

  touch $out
''
