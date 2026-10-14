# written by hand: treefmt-nix's mkFormatterModule is internal and takes the
# package from pkgs
{
  lib,
  pkgs,
  config,
  ...
}:
let
  inherit (lib) mkOption types;
  cfg = config.programs.ai-tells-lint;
  settingsFormat = pkgs.formats.toml { };
in
{
  options.programs.ai-tells-lint = {
    enable = lib.mkEnableOption "ai-tells-lint";

    package = mkOption {
      type = types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalMD "ai-tells-lint built with `pkgs`";
      description = "The ai-tells-lint package to use.";
    };

    includes = mkOption {
      type = types.listOf types.str;
      default = [
        "*.md"
        "*.nix"
        "*.sh"
        "*.py"
      ];
      description = "Files to lint. Supports globbing.";
    };

    excludes = mkOption {
      type = types.listOf types.str;
      default = [ ];
      description = "Files not to lint. Supports globbing. Takes precedence over `includes`.";
    };

    settings = mkOption {
      inherit (settingsFormat) type;
      default = { };
      example = {
        ignore = [ "em-dash" ];
        allow.ai-vocabulary = [ "leverage" ];
      };
      description = ''
        Contents of `.ai-tells-lint.toml`, passed with `--config`. When empty,
        ai-tells-lint reads the nearest `.ai-tells-lint.toml` instead.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    settings.formatter.ai-tells-lint = {
      command = cfg.package;
      options = lib.optionals (cfg.settings != { }) [
        "--config"
        (toString (settingsFormat.generate "ai-tells-lint.toml" cfg.settings))
      ];
      inherit (cfg) includes excludes;
    };
  };
}
