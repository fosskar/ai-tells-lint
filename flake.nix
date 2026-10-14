{
  description = "ai-tells-lint: flag LLM writing tells in markdown prose and code comments";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs =
    {
      self,
      nixpkgs,
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (pkgs: rec {
        ai-tells-lint = pkgs.callPackage ./nix/package.nix { };
        default = ai-tells-lint;
      });

      checks = forAllSystems (
        pkgs:
        let
          inherit (self.packages.${pkgs.stdenv.hostPlatform.system}) ai-tells-lint;
        in
        {
          inherit ai-tells-lint;
          inherit (ai-tells-lint.passthru.tests) unit cli;
        }
      );
    };
}
