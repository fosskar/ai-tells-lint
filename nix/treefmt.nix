{
  imports = [ ./treefmt-module.nix ];

  projectRootFile = "flake.nix";

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
      # both contain tells on purpose
      excludes = [
        "fixtures/*"
        "rules.toml"
      ];
    };
  };

  settings.formatter.ruff-check.options = [ "--no-cache" ];
  settings.formatter.ruff-format.options = [ "--no-cache" ];
}
