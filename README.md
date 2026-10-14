<!-- prettier-ignore -->
<div align="center">

# ai-tells-lint

**A report-only linter for LLM writing tells in markdown prose and in nix, shell and python comments.**

[![treefmt-nix module](https://img.shields.io/badge/treefmt--nix-module-5277C3?style=flat-square&logo=nixos&logoColor=white)](#with-treefmt-nix)
[![Python](https://img.shields.io/badge/Python-standard_library_only-3776AB?style=flat-square&logo=python&logoColor=white)](./ai_tells_lint.py)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

[Usage](#usage) • [Configuration](#configuration) • [Rules](#rules) • [Development](#development) • [Credits](#credits)

</div>

ai-tells-lint reads files and prints each phrase that LLMs overuse: em dashes, inflated vocabulary, chatbot pleasantries, citation artefacts and similar patterns. It changes nothing; you rewrite the sentence or allow the phrase. It runs as a treefmt formatter, so `nix fmt` and the treefmt flake check fail while a tell is left.

> [!NOTE]
> ai-tells-lint is not meant to hide that you write with AI help or publish AI-generated text. Disclose that where it matters, for example with an `Assisted-by:` trailer in commits.
>
> It is meant to make such text less annoying to read. LLM output is often wordy and vague, uses odd terms and inflated words, and repeats the same stock phrases. Readers notice these patterns and get tired of them. ai-tells-lint flags them, so you can let an LLM help you write without making other people read slop.

## Usage

```console
$ ai-tells-lint fixtures/hits.sh
fixtures/hits.sh:2:15: copula-dodge: inflated copula; write "is" or "are": serves as the
fixtures/hits.sh:3:13: ai-vocabulary: word overused by LLMs; use a plainer or more specific word: pivotal
fixtures/hits.sh:3:26: em-dash: em dash; use a comma, colon, parentheses or a new sentence: —
```

Each hit is one line: `path:line:col: rule-id: message: match`. The exit status is 0 without hits, 1 with hits, and 2 when a file cannot be read or scanned, its type is not supported, or the configuration is invalid.

The file suffix selects what is scanned:

| Suffix | Scanned text                                                                                                      |
| ------ | ----------------------------------------------------------------------------------------------------------------- |
| `.md`  | Prose. Fenced code, HTML comments and tags, inline code, URLs, link targets and double-quoted text are skipped.   |
| `.nix` | `#` and `/* */` comments, including comments inside `${ }` interpolations. Strings are skipped.                   |
| `.sh`  | `#` comments. Strings, parameter expansions such as `${a#b}`, heredoc bodies and the shebang line are skipped.    |
| `.py`  | `#` comments, found with the python tokenizer. Strings and docstrings are skipped, and so is a shebang on line 1. |

Words and phrases match only as whole words, case-insensitive, and phrases match across line breaks. A rule with `raw = true` also looks inside code, quotes and URLs, which is how `markup-artefact` finds tracking parameters in links.

### With treefmt-nix

Add the flake input:

```nix
{
  inputs.ai-tells-lint = {
    url = "github:fosskar/ai-tells-lint";
    inputs.nixpkgs.follows = "nixpkgs";
  };
}
```

With [flake-parts](https://flake.parts) and `treefmt-nix.flakeModule`, import the module into `perSystem.treefmt`:

```nix
{ inputs, ... }:
{
  imports = [ inputs.treefmt-nix.flakeModule ];

  perSystem.treefmt = {
    imports = [ inputs.ai-tells-lint.treefmtModules.default ];

    programs.ai-tells-lint = {
      enable = true;
      excludes = [ "vendor/*" ];
      settings = {
        ignore = [ "em-dash" ];
        allow.ai-vocabulary = [ "leverage" ];
      };
    };
  };
}
```

Without flake-parts, import it where you call `treefmt-nix.lib.evalModule`:

```nix
treefmt-nix.lib.evalModule pkgs {
  imports = [ ai-tells-lint.treefmtModules.default ];
  projectRootFile = "flake.nix";
  programs.ai-tells-lint.enable = true;
}
```

`nix fmt` then runs ai-tells-lint with your other formatters and fails on a hit, and so does the treefmt flake check where you expose one (`treefmt-nix.flakeModule` does by default).

| Option                            | Default                            | Description                                                                                                         |
| --------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `programs.ai-tells-lint.enable`   | `false`                            | Run ai-tells-lint as a treefmt formatter.                                                                           |
| `programs.ai-tells-lint.package`  | built with your `pkgs`             | The ai-tells-lint package.                                                                                          |
| `programs.ai-tells-lint.includes` | `[ "*.md" "*.nix" "*.sh" "*.py" ]` | Files to lint.                                                                                                      |
| `programs.ai-tells-lint.excludes` | `[ ]`                              | Files not to lint. Takes precedence over `includes`.                                                                |
| `programs.ai-tells-lint.settings` | `{ }`                              | The [configuration](#configuration), passed with `--config`. When empty, ai-tells-lint reads `.ai-tells-lint.toml`. |

ai-tells-lint has no file include or exclude settings of its own; treefmt's `includes` and `excludes` decide which files it sees.

## Configuration

Without `--config PATH`, ai-tells-lint reads `.ai-tells-lint.toml` from the working directory or the nearest parent directory that has one. Without a file, all built-in rules run unchanged.

```toml
# run only these rules
select = ["em-dash", "ai-vocabulary", "ticket-id"]
# skip these rules; applied after select
ignore = ["em-dash"]

# add entries to a words or phrases rule
[extend]
ai-vocabulary = ["synergy"]

# remove entries from a words or phrases rule
[allow]
ai-vocabulary = ["leverage", "genuinely"]

# add a rule
[[rule]]
id = "ticket-id"
message = "ticket id in prose; link the ticket"
regex = ['\bJIRA-\d+']
examples = ["see JIRA-12"]
```

| Key           | Value                | Description                                                                                                                                            |
| ------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `select`      | list of rule ids     | Run only these rules. Default: all rules.                                                                                                              |
| `ignore`      | list of rule ids     | Do not run these rules.                                                                                                                                |
| `extend.<id>` | list of strings      | Add words or phrases to a `words` or `phrases` rule.                                                                                                   |
| `allow.<id>`  | list of strings      | Remove words or phrases from a `words` or `phrases` rule. Matching is case-insensitive, and each entry must be in the rule. Removing all turns it off. |
| `[[rule]]`    | array of rule tables | Add rules, in the same schema as [`rules.toml`](./rules.toml).                                                                                         |

A rule table has these keys:

| Key                         | Description                                                                                       |
| --------------------------- | ------------------------------------------------------------------------------------------------- |
| `id`                        | Lowercase words joined by `-`. Must not repeat a built-in id.                                     |
| `message`                   | Printed with each hit.                                                                            |
| `words`, `phrases`, `regex` | Exactly one of them: a list of words, of phrases, or of python regular expressions (ignore case). |
| `raw`                       | `true` to also match inside code, quotes and URLs. Default `false`.                               |
| `examples`, `source`        | Optional. Example sentences and where the rule comes from, for documentation.                     |

The ids in `select`, `ignore`, `extend` and `allow` can name built-in and added rules. An unknown key or rule id, a wrong type, or a regex that does not compile exits 2 with a message that names the key or rule.

## Rules

[`rules.toml`](./rules.toml) holds the built-in rules with their word lists, a `source` for each and an example the unit tests check.

| Rule                     | Flags                                                                                              |
| ------------------------ | -------------------------------------------------------------------------------------------------- |
| `em-dash`                | The em dash character.                                                                             |
| `ai-vocabulary`          | Single words that LLMs overuse.                                                                    |
| `delve`                  | `delve into` and its forms.                                                                        |
| `copula-dodge`           | `serves as a` and similar phrases in place of `is`.                                                |
| `puffery`                | Promotional phrases that inflate significance, such as `nestled in`.                               |
| `plays-a-role`           | `plays a crucial role` and its variants.                                                           |
| `didactic-hedge`         | `it is important to note` and similar lead-ins.                                                    |
| `vague-attribution`      | Claims attributed to unnamed experts or studies.                                                   |
| `challenges-boilerplate` | Closing sentences about remaining challenges and an uncertain future.                              |
| `chatbot-phrase`         | Chat replies left in the text: greetings, offers to help, knowledge cutoff disclaimers.            |
| `negative-parallelism`   | `not just X, but Y` and `it is not X, it is Y`.                                                    |
| `performative-honesty`   | `to be honest`, `let me be clear` and similar.                                                     |
| `staged-reveal`          | Lead-ins that announce a point before making it.                                                   |
| `participle-tail`        | A trailing `, highlighting its ...` clause that adds commentary.                                   |
| `signposting`            | Explainer phrases that announce the structure of the text.                                         |
| `therapy-voice`          | Counselling phrases such as `sit with that`.                                                       |
| `stilted-wording`        | Formal or literary wording where an everyday phrase exists, such as `tire of`.                     |
| `markup-artefact`        | Chatbot citation markup, `utm_source` tracking parameters and AI attribution lines, also in links. |

## Development

```bash
nix develop

# unit tests
python3 -m unittest -v test_ai_tells_lint

# lint the fixtures
python3 ai_tells_lint.py fixtures/hits.*

# format and lint the repo, ai-tells-lint included
nix fmt

# formatting, package, unit, cli and treefmt module checks
nix flake check
```

`fixtures/` and `rules.toml` contain tells on purpose and are excluded from the repo's own lint.

## Credits

These sources documented the patterns the rules look for. They are listed from primary to derived: the later ones build on the earlier ones. Each rule's `source` field in `rules.toml` names the ones it builds on. The rules themselves are written for ai-tells-lint: word and phrase lists are sorted alphabetically, and the regular expressions were written from plain descriptions of each pattern.

- **[Wikipedia: Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)**: words from its list of AI vocabulary, and the categories behind several rules: undue emphasis, vague attributions, negative parallelisms, superficial analyses, collaborative communication and reference markup bugs.
- **[LLM cliche highlighter](https://tools.simonwillison.net/llm-cliche-highlighter)** by Simon Willison: the patterns behind most regex rules. Part of its patterns are adapted from the Wikipedia guide.
- **[vale-ai-tells](https://github.com/tbhb/vale-ai-tells)** by Tony Burns: words and phrases from its Vale styles, for example `EmDashUsage`, `OverusedVocabulary`, `ServesAsDodge`, `PromotionalPuffery` and `ClosingPleasantries`.
- **Farid Zakaria**: the post [Hiding my AI slop from my Nix friends](https://fzakaria.com/2026/09/28/hiding-my-ai-slop-from-my-nix-friends), `writingStyle` in [nix-home `agent-settings.nix`](https://github.com/fzakaria/nix-home/blob/master/users/fmzakari/agent-settings.nix) and [omnibin `tools/check-prose.py`](https://github.com/fzakaria/omnibin/blob/fc56e228eaf26407d976d59f4dcda306ead87345/tools/check-prose.py), which build on the Wikipedia guide and the highlighter: the idea of a deterministic prose check in the build, and words and phrases for several rules. His `check-prose.py` is a standalone script run as a flake check; ai-tells-lint is a treefmt formatter instead, so it plugs into an existing treefmt-nix setup.
- **[A Hacker News comment by tyre](https://news.ycombinator.com/item?id=49413456)**, a personal list of banned phrases posted under Fabien Sanglard's [My agent.md to improve LLM-assisted code quality](https://fabiensanglard.net/agent.md/index.html): words and phrases for eight rules, which cite it as "HN tyre".

Related, not a rule source: [proselint](https://github.com/amperser/proselint) (BSD-3-Clause) and its Vale port [vale-cli/proselint](https://github.com/vale-cli/proselint) check general prose quality.
