{
  imports = [ ./treefmt-module.nix ];

  projectRootFile = "flake.nix";

  # test inputs: tells on purpose, and reformatting would move the expected
  # columns
  settings.global.excludes = [ "fixtures/*" ];

  programs = {
    nixfmt.enable = true;
    deadnix.enable = true;
    statix.enable = true;
    ruff-check = {
      enable = true;
      extendSelect = [ "I" ];
    };
    ruff-format.enable = true;
    taplo.enable = true;
    prettier.enable = true;
    ai-tells-lint = {
      enable = true;
      # contains tells on purpose
      excludes = [ "rules.toml" ];
    };
  };

  settings.formatter.ruff-check.options = [ "--no-cache" ];
  settings.formatter.ruff-format.options = [ "--no-cache" ];
}
