{
  description = "ai-tells-lint: flag LLM writing tells in markdown prose and code comments";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    nixbot = {
      url = "github:Mic92/nixbot";
      inputs.nixpkgs.follows = "nixpkgs";
      inputs.treefmt-nix.follows = "treefmt-nix";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      treefmt-nix,
      nixbot,
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      treefmtFor = forAllSystems (pkgs: treefmt-nix.lib.evalModule pkgs ./nix/treefmt.nix);
    in
    {
      # nixbot scheduled effects: flake input updates
      herculesCI = import ./nix/effects.nix {
        pkgs = nixpkgs.legacyPackages.x86_64-linux;
        inherit nixbot;
      };

      packages = forAllSystems (pkgs: rec {
        ai-tells-lint = pkgs.callPackage ./nix/package.nix { };
        default = ai-tells-lint;
      });

      treefmtModules.default = ./nix/treefmt-module.nix;

      checks = forAllSystems (
        pkgs:
        let
          inherit (self.packages.${pkgs.stdenv.hostPlatform.system}) ai-tells-lint;
        in
        {
          formatting = treefmtFor.${pkgs.stdenv.hostPlatform.system}.config.build.check self;
          inherit ai-tells-lint;
          inherit (ai-tells-lint.passthru.tests) unit cli;
          treefmt-module = pkgs.callPackage ./nix/treefmt-module-test.nix {
            inherit treefmt-nix;
            treefmtModule = self.treefmtModules.default;
          };
        }
      );

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.python3
            treefmtFor.${pkgs.stdenv.hostPlatform.system}.config.build.wrapper
          ];
        };
      });

      formatter = forAllSystems (
        pkgs: treefmtFor.${pkgs.stdenv.hostPlatform.system}.config.build.wrapper
      );
    };
}
