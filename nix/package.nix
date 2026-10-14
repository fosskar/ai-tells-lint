{
  lib,
  stdenvNoCC,
  python3,
  makeWrapper,
  runCommand,
}:
let
  testSrc = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../test_ai_tells_lint.py
      ../fixtures
    ];
  };
in
stdenvNoCC.mkDerivation (finalAttrs: {
  pname = "ai-tells-lint";
  version = "0.1.0";

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../ai_tells_lint.py
      ../rules.toml
    ];
  };

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    runHook preInstall

    install -Dm644 -t $out/share/ai-tells-lint ai_tells_lint.py rules.toml
    makeWrapper ${python3.interpreter} $out/bin/ai-tells-lint \
      --add-flags $out/share/ai-tells-lint/ai_tells_lint.py

    runHook postInstall
  '';

  passthru.tests = {
    unit = runCommand "ai-tells-lint-test-unit" { nativeBuildInputs = [ python3 ]; } ''
      cp ${finalAttrs.finalPackage}/share/ai-tells-lint/* .
      cp -r ${testSrc}/. .
      python3 -m unittest -v test_ai_tells_lint
      touch $out
    '';

    cli =
      runCommand "ai-tells-lint-test-cli"
        {
          nativeBuildInputs = [ finalAttrs.finalPackage ];
        }
        ''
          cd ${testSrc}/fixtures

          ai-tells-lint clean.md clean.nix clean.sh clean.py

          status=0
          ai-tells-lint hits.md hits.nix hits.sh hits.py >"$NIX_BUILD_TOP/hits.out" || status=$?
          [ "$status" -eq 1 ]
          if grep -Ev '^hits\.(md|nix|sh|py):[0-9]+:[0-9]+: [a-z-]+: .+: .+$' "$NIX_BUILD_TOP/hits.out"; then
            exit 1
          fi
          [ "$(wc -l <"$NIX_BUILD_TOP/hits.out")" -eq 18 ]

          status=0
          ai-tells-lint ${finalAttrs.finalPackage}/share/ai-tells-lint/rules.toml || status=$?
          [ "$status" -eq 2 ]

          touch $out
        '';
  };

  meta = {
    description = "flag LLM writing tells in markdown prose and nix, shell and python comments";
    mainProgram = "ai-tells-lint";
    license = lib.licenses.mit;
    platforms = lib.platforms.all;
  };
})
