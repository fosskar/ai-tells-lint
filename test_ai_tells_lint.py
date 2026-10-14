import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

import ai_tells_lint

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
RULES = ai_tells_lint.load_rules()

EXPECTED_HITS = {
    "hits.md": [
        (3, "em-dash", "—"),
        (4, "copula-dodge", "serves as the"),
        (5, "ai-vocabulary", "pivotal"),
        (6, "negative-parallelism", "is not just"),
        (7, "em-dash", "—"),
        (8, "chatbot-phrase", "I hope"),
        (10, "markup-artefact", "utm_source=chatgpt.com"),
    ],
    "hits.nix": [
        (1, "copula-dodge", "serves as the"),
        (3, "ai-vocabulary", "pivotal"),
        (4, "em-dash", "—"),
        (5, "negative-parallelism", "is not just"),
    ],
    "hits.sh": [
        (2, "copula-dodge", "serves as the"),
        (3, "ai-vocabulary", "pivotal"),
        (3, "em-dash", "—"),
    ],
    "hits.go": [
        (1, "copula-dodge", "serves as the"),
        (4, "ai-vocabulary", "pivotal"),
        (5, "em-dash", "—"),
        (7, "negative-parallelism", "is not just"),
    ],
    "hits.js": [
        (1, "copula-dodge", "serves as the"),
        (2, "ai-vocabulary", "pivotal"),
        (2, "em-dash", "—"),
        (4, "negative-parallelism", "is not just"),
        (7, "chatbot-phrase", "I hope"),
    ],
    "hits.rs": [
        (1, "copula-dodge", "serves as the"),
        (3, "ai-vocabulary", "pivotal"),
        (3, "em-dash", "—"),
        (5, "negative-parallelism", "is not just"),
    ],
    "hits.c": [
        (1, "copula-dodge", "serves as the"),
        (4, "ai-vocabulary", "pivotal"),
        (4, "em-dash", "—"),
        (5, "negative-parallelism", "is not just"),
    ],
    "hits.java": [
        (1, "copula-dodge", "serves as the"),
        (5, "ai-vocabulary", "pivotal"),
        (5, "em-dash", "—"),
        (6, "negative-parallelism", "is not just"),
    ],
    "hits.yaml": [
        (1, "copula-dodge", "serves as the"),
        (2, "ai-vocabulary", "pivotal"),
        (2, "em-dash", "—"),
        (4, "negative-parallelism", "is not just"),
    ],
    "hits.toml": [
        (1, "copula-dodge", "serves as the"),
        (2, "ai-vocabulary", "pivotal"),
        (2, "em-dash", "—"),
        (3, "negative-parallelism", "is not just"),
    ],
    "hits.py": [
        (1, "copula-dodge", "serves as the"),
        (2, "ai-vocabulary", "pivotal"),
        (2, "em-dash", "—"),
        (3, "negative-parallelism", "is not just"),
    ],
}


def lint(text, kind):
    return [(h.line, h.col, h.rule) for h in ai_tells_lint.lint(text, kind, RULES)]


def rule_ids(text, kind):
    return [rule for _, _, rule in lint(text, kind)]


class Fixtures(unittest.TestCase):
    def test_hits(self):
        for name, expected in EXPECTED_HITS.items():
            with self.subTest(name):
                path = FIXTURES / name
                lines = path.read_text().splitlines()
                want = sorted(
                    (line, lines[line - 1].index(anchor) + 1, rule)
                    for line, rule, anchor in expected
                )
                got = lint(path.read_text(), path.suffix[1:])
                self.assertEqual(got, want)

    def test_clean(self):
        for kind in ai_tells_lint.SCANNERS:
            with self.subTest(kind):
                path = FIXTURES / f"clean.{kind}"
                self.assertEqual(lint(path.read_text(), kind), [])

    def test_every_kind_has_fixtures(self):
        self.assertEqual(
            sorted(EXPECTED_HITS), sorted(f"hits.{k}" for k in ai_tells_lint.SCANNERS)
        )


class Rules(unittest.TestCase):
    def test_rule_shape(self):
        ids = [r.id for r in RULES]
        self.assertEqual(len(ids), len(set(ids)))
        for rule in RULES:
            with self.subTest(rule.id):
                self.assertRegex(rule.id, r"^[a-z]+(-[a-z]+)*$")
                self.assertTrue(rule.message)
                self.assertIn(rule.kind, ("words", "phrases", "regex"))

    def test_each_rule_matches_its_examples(self):
        for rule in RULES:
            with self.subTest(rule.id):
                self.assertTrue(rule.examples)
                for example in rule.examples:
                    self.assertIn(rule.id, rule_ids(example, "md"), example)

    def test_rule_types_present(self):
        self.assertEqual({r.kind for r in RULES}, {"words", "phrases", "regex"})


class Markdown(unittest.TestCase):
    def test_tilde_fence(self):
        self.assertEqual(lint("~~~\npivotal\n~~~\n", "md"), [])

    def test_unclosed_fence_skips_rest(self):
        self.assertEqual(lint("```\npivotal\n", "md"), [])

    def test_double_backtick_span(self):
        self.assertEqual(lint("use ``a `pivotal` b`` here\n", "md"), [])

    def test_code_span_across_lines(self):
        self.assertEqual(lint("use `a\npivotal` here\n", "md"), [])

    def test_quote_does_not_cross_paragraphs(self):
        text = 'a "stray quote\n\nthe pivotal part "x"\n'
        self.assertEqual(rule_ids(text, "md"), ["ai-vocabulary"])

    def test_multiline_html_comment(self):
        self.assertEqual(lint("<!--\npivotal\n-->\n", "md"), [])

    def test_reference_link_definition(self):
        self.assertEqual(lint("[x]: https://example.com/pivotal\n", "md"), [])

    def test_identifier_boundaries(self):
        self.assertEqual(lint("set pivotal_mode or ./pivotal/x\n", "md"), [])

    def test_word_at_sentence_end(self):
        self.assertEqual(rule_ids("this is pivotal.\n", "md"), ["ai-vocabulary"])

    def test_case_insensitive(self):
        self.assertEqual(rule_ids("Pivotal changes\n", "md"), ["ai-vocabulary"])

    def test_curly_apostrophe(self):
        self.assertIn(
            "chatbot-phrase", rule_ids("Don\u2019t hesitate to reach out\n", "md")
        )

    def test_stilted_wording_spares_the_everyday_form(self):
        self.assertEqual(rule_ids("readers tire of it\n", "md"), ["stilted-wording"])
        self.assertEqual(lint("readers get tired of it\n", "md"), [])

    def test_raw_rule_ignores_masking_but_others_do_not(self):
        text = "see `oaicite` and https://x.test/pivotal?utm_source=openai\n"
        self.assertEqual(rule_ids(text, "md"), ["markup-artefact", "markup-artefact"])


class Nix(unittest.TestCase):
    def test_block_comment(self):
        text = "{\n  a = /* the pivotal value */ 1;\n}\n"
        self.assertEqual(lint(text, "nix"), [(2, 14, "ai-vocabulary")])

    def test_multiline_block_comment(self):
        text = "/*\n  I hope this helps\n*/\n{ }\n"
        self.assertEqual(rule_ids(text, "nix"), ["chatbot-phrase"])

    def test_interpolation_comment(self):
        text = '"${\n  # pivotal\n  x\n}"\n'
        self.assertEqual(rule_ids(text, "nix"), ["ai-vocabulary"])

    def test_indented_string_escapes(self):
        text = "''\n  ''$ ''' ''\\n # pivotal\n''\n"
        self.assertEqual(lint(text, "nix"), [])

    def test_dollar_dollar_brace(self):
        text = '"$${ # pivotal }"\n'
        self.assertEqual(lint(text, "nix"), [])

    def test_path_with_star_is_not_comment(self):
        self.assertEqual(lint("x = ./a/b; # see machines/*/x.nix\n", "nix"), [])

    def test_comment_skips_code_quotes(self):
        self.assertEqual(lint('# use "pivotal" or `pivotal`\n', "nix"), [])


class Shell(unittest.TestCase):
    def test_quoted_heredoc_with_dash(self):
        text = "cat <<-'EOF'\n\t# pivotal\n\tEOF\n# pivotal\n"
        self.assertEqual(lint(text, "sh"), [(4, 3, "ai-vocabulary")])

    def test_hash_inside_word_and_parameter(self):
        text = "a=b#pivotal\necho ${a#pivotal} ${#a} $#\n"
        self.assertEqual(lint(text, "sh"), [])

    def test_escaped_hash(self):
        self.assertEqual(lint("echo \\# pivotal\n", "sh"), [])

    def test_comment_after_semicolon(self):
        self.assertEqual(rule_ids("true;# pivotal\n", "sh"), ["ai-vocabulary"])

    def test_herestring_is_not_heredoc(self):
        text = "cat <<< x\n# pivotal\n"
        self.assertEqual(rule_ids(text, "sh"), ["ai-vocabulary"])


class Python(unittest.TestCase):
    def test_docstring_skipped(self):
        self.assertEqual(lint('def f():\n    """pivotal"""\n', "py"), [])

    def test_hash_in_string(self):
        self.assertEqual(lint('x = "# pivotal"\n', "py"), [])

    def test_unparsable_source(self):
        with self.assertRaises(ai_tells_lint.ScanError):
            ai_tells_lint.lint('x = """\n', "py", RULES)


def configured(config, text, kind="md"):
    rules = ai_tells_lint.configure(RULES, config)
    return [h.rule for h in ai_tells_lint.lint(text, kind, rules)]


class Go(unittest.TestCase):
    def test_block_comment(self):
        text = "var a = /* the pivotal value */ 1\n"
        self.assertEqual(lint(text, "go"), [(1, 16, "ai-vocabulary")])

    def test_raw_string(self):
        self.assertEqual(lint("var a = `\n// pivotal\n`\n", "go"), [])

    def test_rune_quote_does_not_open_string(self):
        text = "var c = '\"' // a pivotal step\n"
        self.assertEqual(rule_ids(text, "go"), ["ai-vocabulary"])


class JavaScript(unittest.TestCase):
    def test_doc_comment_stars_do_not_break_phrases(self):
        text = "/**\n * it serves\n * as the gate\n */\nconst a = 1;\n"
        self.assertEqual(rule_ids(text, "js"), ["copula-dodge"])

    def test_template_literal(self):
        text = "const a = `// pivotal ${b /* I hope this helps */} pivotal`;\n"
        self.assertEqual(rule_ids(text, "js"), ["chatbot-phrase"])

    def test_nested_template_literal(self):
        text = "const a = `${`// pivotal ${c}`}`; // pivotal\n"
        self.assertEqual(lint(text, "js"), [(1, 38, "ai-vocabulary")])

    def test_regex_literal(self):
        text = 'const r = /\\/\\/ pivotal "[/]/g;\n// pivotal\n'
        self.assertEqual(lint(text, "js"), [(2, 4, "ai-vocabulary")])

    def test_division_is_not_regex(self):
        text = "const d = a / 2; // a pivotal step\n"
        self.assertEqual(rule_ids(text, "js"), ["ai-vocabulary"])

    def test_single_quoted_string(self):
        self.assertEqual(lint("const a = '// pivotal';\n", "js"), [])


class Rust(unittest.TestCase):
    def test_lifetimes_are_not_char_literals(self):
        text = "fn f<'a>(x: &'a str) -> &'a str { x } // pivotal\n"
        self.assertEqual(rule_ids(text, "rs"), ["ai-vocabulary"])

    def test_char_and_byte_literals(self):
        text = "let a = '\"'; let b = b'\\''; // pivotal\n"
        self.assertEqual(rule_ids(text, "rs"), ["ai-vocabulary"])

    def test_raw_string(self):
        self.assertEqual(lint('let a = r#"// pivotal "x" pivotal"#;\n', "rs"), [])

    def test_doc_comments(self):
        text = "//! the pivotal crate\n/// the pivotal fn\nfn f() {}\n"
        self.assertEqual(
            lint(text, "rs"), [(1, 9, "ai-vocabulary"), (2, 9, "ai-vocabulary")]
        )

    def test_block_comments_nest(self):
        text = "/* a /* b */ pivotal */\nfn f() {}\n"
        self.assertEqual(rule_ids(text, "rs"), ["ai-vocabulary"])


class C(unittest.TestCase):
    def test_block_comments_do_not_nest(self):
        self.assertEqual(lint("/* a /* b */ pivotal */\n", "c"), [])

    def test_escaped_char_literal(self):
        text = "char c = '\\''; // a pivotal step\n"
        self.assertEqual(rule_ids(text, "c"), ["ai-vocabulary"])


class Java(unittest.TestCase):
    def test_text_block(self):
        text = 'String s = """\n  // pivotal "quoted"\n  """; // pivotal\n'
        self.assertEqual(lint(text, "java"), [(3, 11, "ai-vocabulary")])


class Yaml(unittest.TestCase):
    def test_comment_needs_preceding_space(self):
        text = "url: https://example.com/#pivotal\na: b # pivotal\n"
        self.assertEqual(lint(text, "yaml"), [(2, 8, "ai-vocabulary")])

    def test_quoted_scalars(self):
        text = "a: \"x # pivotal\"\nb: 'it''s # pivotal'\n- 'x' # pivotal\n"
        self.assertEqual(lint(text, "yaml"), [(3, 9, "ai-vocabulary")])

    def test_apostrophe_in_plain_scalar(self):
        self.assertEqual(rule_ids("a: don't # pivotal\n", "yaml"), ["ai-vocabulary"])

    def test_block_scalar(self):
        text = "steps:\n  - run: |\n      # pivotal\n      echo\n  # pivotal\n"
        self.assertEqual(lint(text, "yaml"), [(5, 5, "ai-vocabulary")])

    def test_block_scalar_header_comment(self):
        text = "a: >- # pivotal\n  # not a comment, pivotal\n"
        self.assertEqual(lint(text, "yaml"), [(1, 9, "ai-vocabulary")])


class Toml(unittest.TestCase):
    def test_strings(self):
        text = "a = \"x # pivotal\" # pivotal\nb = 'y # pivotal'\n"
        self.assertEqual(lint(text, "toml"), [(1, 21, "ai-vocabulary")])

    def test_multiline_strings(self):
        text = "a = \"\"\"\n# pivotal\n\"\"\"\nb = '''\n# pivotal\n'''\n"
        self.assertEqual(lint(text, "toml"), [])


class Suffixes(unittest.TestCase):
    def test_every_suffix_has_a_scanner(self):
        for suffix, kind in ai_tells_lint.SUFFIXES.items():
            with self.subTest(suffix):
                self.assertIn(kind, ai_tells_lint.SCANNERS)


class Suppression(unittest.TestCase):
    def test_allow_on_same_line(self):
        text = "a pivotal step <!-- ai-tells-lint: allow ai-vocabulary -->\n"
        self.assertEqual(lint(text, "md"), [])

    def test_allow_names_other_rule(self):
        text = "a pivotal step <!-- ai-tells-lint: allow em-dash -->\n"
        self.assertEqual(rule_ids(text, "md"), ["ai-vocabulary"])

    def test_allow_several_rules(self):
        text = "a pivotal \u2014 step # ai-tells-lint: allow em-dash, ai-vocabulary\n"
        self.assertEqual(lint("x = 1 # " + text, "nix"), [])

    def test_bare_allow_covers_all_rules(self):
        self.assertEqual(
            lint("x = 1  # a pivotal \u2014 step ai-tells-lint: allow\n", "py"), []
        )

    def test_allow_next_line(self):
        text = "<!-- ai-tells-lint: allow-next-line -->\npivotal\npivotal\n"
        self.assertEqual(lint(text, "md"), [(3, 1, "ai-vocabulary")])

    def test_allow_next_line_in_comment(self):
        text = "# ai-tells-lint: allow-next-line ai-vocabulary\n# pivotal\n# pivotal\n"
        self.assertEqual(lint(text, "sh"), [(3, 3, "ai-vocabulary")])

    def test_off_and_on(self):
        text = "pivotal\n<!-- ai-tells-lint: off -->\npivotal\n\npivotal\n<!-- ai-tells-lint: on -->\npivotal\n"
        self.assertEqual(
            lint(text, "md"), [(1, 1, "ai-vocabulary"), (7, 1, "ai-vocabulary")]
        )

    def test_multiline_hit_uses_start_line(self):
        text = "it serves <!-- ai-tells-lint: allow -->\nas the gate\n"
        self.assertEqual(lint(text, "md"), [])

    def test_marker_outside_comments_is_ignored(self):
        for text, kind in (
            ("`ai-tells-lint: off`\n\npivotal\n", "md"),
            ("```\n<!-- ai-tells-lint: off -->\n```\npivotal\n", "md"),
            ('x = "ai-tells-lint: off"  # pivotal\n', "py"),
        ):
            with self.subTest(text):
                self.assertEqual(rule_ids(text, kind), ["ai-vocabulary"])


class MinHits(unittest.TestCase):
    def test_rule_key(self):
        rules = ai_tells_lint.configure(
            RULES,
            {
                "rule": [
                    {"id": "x", "message": "m", "words": ["foo", "bar"], "min-hits": 2}
                ]
            },
        )
        text = "foo alone\n\nfoo and bar\n"
        got = [
            (h.line, h.rule)
            for h in ai_tells_lint.lint(text, "md", rules)
            if h.rule == "x"
        ]
        self.assertEqual(got, [(3, "x"), (3, "x")])

    def test_config_override(self):
        config = {"min-hits": {"ai-vocabulary": 2}}
        self.assertEqual(configured(config, "a pivotal step\n"), [])
        self.assertEqual(
            configured(config, "a pivotal step,\na vibrant one\n"),
            ["ai-vocabulary", "ai-vocabulary"],
        )

    def test_comment_block_is_one_segment(self):
        config = {"min-hits": {"ai-vocabulary": 2}}
        self.assertEqual(
            configured(config, "# pivotal\n# vibrant\nx = 1\n", "nix"),
            ["ai-vocabulary", "ai-vocabulary"],
        )

    def test_suppressed_hits_do_not_count(self):
        config = {"min-hits": {"ai-vocabulary": 2}}
        text = "pivotal <!-- ai-tells-lint: allow -->\nvibrant\n"
        self.assertEqual(configured(config, text), [])

    def test_bad_values(self):
        for config in (
            {"min-hits": {"ai-vocabulary": 0}},
            {"min-hits": {"ai-vocabulary": True}},
            {"min-hits": {"ai-vocabulary": "2"}},
            {"min-hits": {"em-dahs": 2}},
            {"rule": [{"id": "x", "message": "m", "words": ["a"], "min-hits": 0}]},
        ):
            with (
                self.subTest(config),
                self.assertRaises(ai_tells_lint.ConfigError),
            ):
                ai_tells_lint.configure(RULES, config)


class PerFileIgnores(unittest.TestCase):
    def test_validation(self):
        for config in (
            {"per-file-ignores": {"docs/*": ["em-dahs"]}},
            {"per-file-ignores": {"docs/*": "em-dash"}},
            {"per-file-ignores": ["docs/*"]},
        ):
            with (
                self.subTest(config),
                self.assertRaises(ai_tells_lint.ConfigError),
            ):
                ai_tells_lint.configure(RULES, config)


class CorpusFalsePositives(unittest.TestCase):
    # wrong hits found by linting pre-2022 human text; see the corpus study
    def test_chinese_dash(self):
        self.assertEqual(lint("这是一个例子\u2014\u2014它很简单。\n", "md"), [])

    def test_doubled_dash(self):
        self.assertEqual(lint("a\u2014\u2014b\n", "md"), [])

    def test_unicode_name_full_stop(self):
        self.assertEqual(lint("U+002E is FULL STOP in the table.\n", "md"), [])
        self.assertIn(
            "signposting-emphatic", rule_ids("That is the rule. Full stop.\n", "md")
        )

    def test_not_just_any(self):
        self.assertEqual(lint("We do not just any reads, but writes.\n", "md"), [])

    def test_mid_sentence_exclamations(self):
        for text in (
            "You can of course! use it.\n",
            "Don't hesitate to file a bug.\n",
            "quite frankly, it works\n",
            "to be honest about limits\n",
        ):
            with self.subTest(text):
                self.assertEqual(lint(text, "md"), [])

    def test_sentence_start_opener(self):
        self.assertEqual(
            rule_ids("Certainly! Here is the draft.\n", "md"), ["chatbot-opener"]
        )

    def test_despite_limitations(self):
        self.assertEqual(
            lint("Despite these limitations, the queue is fast.\n", "md"), []
        )

    def test_key_insight_as_noun(self):
        self.assertEqual(
            lint("This gives the key insight into scheduling.\n", "md"), []
        )


class ScannerBugs(unittest.TestCase):
    def test_match_text_drops_comment_markers(self):
        for text, kind in (
            ("/// It is worth\n/// noting that x.\nfn f() {}\n", "rs"),
            ("/**\n * it is worth\n * noting that x\n */\n", "java"),
            ("# it is worth\n# noting that x\n", "nix"),
        ):
            with self.subTest(kind):
                hits = ai_tells_lint.lint(text, kind, RULES)
                self.assertEqual([h.text.lower() for h in hits], ["it is worth noting"])

    def test_indented_code_block(self):
        text = (
            "Run this:\n\n    # it is important to note\n    pivotal --now\n\npivotal\n"
        )
        self.assertEqual(lint(text, "md"), [(6, 1, "ai-vocabulary")])

    def test_indented_list_paragraph_is_prose(self):
        text = "- item\n\n    a pivotal step\n"
        self.assertEqual(rule_ids(text, "md"), ["ai-vocabulary"])

    def test_fence_in_list_item(self):
        text = "1. Install it:\n\n    ```sh\n    x=1\n\n    # pivotal\n    ```\n\npivotal\n"
        self.assertEqual(lint(text, "md"), [(9, 1, "ai-vocabulary")])

    def test_shell_command_substitution_in_string(self):
        text = 'echo "$(printf "%s" "a # pivotal")" # pivotal\n'
        self.assertEqual(lint(text, "sh"), [(1, 39, "ai-vocabulary")])

    def test_js_regex_after_keyword(self):
        text = "function f(s) { return /[//] pivotal x/.test(s); } // pivotal\n"
        self.assertEqual(lint(text, "js"), [(1, 55, "ai-vocabulary")])

    def test_js_division_after_identifier(self):
        text = "const d = total / count; // a pivotal step\n"
        self.assertEqual(rule_ids(text, "js"), ["ai-vocabulary"])


class Config(unittest.TestCase):
    TEXT = "a pivotal step \u2014 we delve into it\n"

    def assertConfigError(self, config, *fragments):
        with self.assertRaises(ai_tells_lint.ConfigError) as ctx:
            ai_tells_lint.configure(RULES, config)
        for fragment in fragments:
            self.assertIn(fragment, str(ctx.exception))

    def test_empty_config_keeps_builtin_rules(self):
        self.assertEqual(ai_tells_lint.configure(RULES, {}), RULES)

    def test_ignore(self):
        self.assertEqual(
            configured({"ignore": ["em-dash", "delve"]}, self.TEXT), ["ai-vocabulary"]
        )

    def test_select(self):
        self.assertEqual(configured({"select": ["delve"]}, self.TEXT), ["delve"])

    def test_ignore_applies_after_select(self):
        config = {"select": ["delve", "em-dash"], "ignore": ["em-dash"]}
        self.assertEqual(configured(config, self.TEXT), ["delve"])

    def test_extend_words(self):
        config = {"extend": {"ai-vocabulary": ["synergy"]}}
        self.assertEqual(configured(config, "real synergy\n"), ["ai-vocabulary"])
        self.assertEqual(configured(config, "a pivotal step\n"), ["ai-vocabulary"])

    def test_extend_phrases(self):
        config = {"extend": {"delve": ["dig into"]}}
        self.assertEqual(configured(config, "we dig\ninto it\n"), ["delve"])

    def test_allow_word(self):
        config = {"allow": {"ai-vocabulary": ["Leverage"]}}
        self.assertEqual(configured(config, "we leverage it\n"), [])
        self.assertEqual(configured(config, "a pivotal step\n"), ["ai-vocabulary"])

    def test_allow_phrase(self):
        config = {"allow": {"copula-dodge": ["serves as the"]}}
        self.assertEqual(configured(config, "it serves as the gate\n"), [])
        self.assertEqual(configured(config, "it serves as a gate\n"), ["copula-dodge"])

    def test_allow_every_entry_disables_rule(self):
        delve = next(r for r in RULES if r.id == "delve")
        config = {"allow": {"delve": list(delve.items)}}
        self.assertEqual(configured(config, "we delve into it, plainly\n"), [])

    def test_custom_rules(self):
        config = {
            "rule": [
                {"id": "synergy", "message": "buzzword", "words": ["synergy"]},
                {
                    "id": "moving-forward",
                    "message": "filler",
                    "phrases": ["moving forward"],
                },
                {
                    "id": "ticket",
                    "message": "ticket id in prose",
                    "regex": [r"\bJIRA-\d+"],
                    "raw": True,
                    "source": "team style guide",
                    "examples": ["see `JIRA-12`"],
                },
            ]
        }
        text = "Moving\nforward, synergy; see `JIRA-12`\n"
        self.assertEqual(
            sorted(configured(config, text)), ["moving-forward", "synergy", "ticket"]
        )

    def test_custom_rule_can_be_extended_and_selected(self):
        config = {
            "rule": [{"id": "synergy", "message": "buzzword", "words": ["synergy"]}],
            "extend": {"synergy": ["synergies"]},
            "select": ["synergy"],
        }
        self.assertEqual(configured(config, "synergies, pivotal\n"), ["synergy"])

    def test_unknown_top_level_key(self):
        self.assertConfigError({"disable": ["em-dash"]}, "disable")

    def test_unknown_rule_ids(self):
        for config in (
            {"ignore": ["em-dahs"]},
            {"select": ["em-dahs"]},
            {"extend": {"em-dahs": ["x"]}},
            {"allow": {"em-dahs": ["x"]}},
        ):
            with self.subTest(config):
                self.assertConfigError(config, "unknown rule id", "em-dahs")

    def test_wrong_types(self):
        for config in (
            {"ignore": "em-dash"},
            {"select": [1]},
            {"extend": ["synergy"]},
            {"allow": {"ai-vocabulary": "leverage"}},
            {"extend": {"ai-vocabulary": [""]}},
            {"rule": {"id": "x"}},
        ):
            with self.subTest(config):
                self.assertConfigError(config)

    def test_extend_regex_rule(self):
        self.assertConfigError({"extend": {"em-dash": ["x"]}}, "em-dash", "regex")

    def test_allow_entry_not_in_rule(self):
        self.assertConfigError(
            {"allow": {"ai-vocabulary": ["synergy"]}}, "ai-vocabulary", "synergy"
        )

    def test_bad_custom_rules(self):
        base = {"id": "x", "message": "m"}
        for rule, fragment in (
            ({**base}, "exactly one of"),
            ({**base, "words": ["a"], "regex": ["b"]}, "exactly one of"),
            ({"id": "x", "words": ["a"]}, "message"),
            ({"message": "m", "words": ["a"]}, "id"),
            ({**base, "id": "Bad Id", "words": ["a"]}, "Bad Id"),
            ({**base, "words": []}, "words"),
            ({**base, "regex": ["("]}, "regex"),
            ({**base, "words": ["a"], "raw": "yes"}, "raw"),
            ({**base, "words": ["a"], "severity": "high"}, "severity"),
            ({**base, "id": "em-dash", "regex": ["x"]}, "em-dash"),
        ):
            with self.subTest(rule):
                self.assertConfigError({"rule": [rule]}, fragment)


class Cli(unittest.TestCase):
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ai_tells_lint.main([str(a) for a in args])
        return code, out.getvalue(), err.getvalue()

    def test_clean_exit_zero(self):
        code, out, _ = self.run_main(*sorted(FIXTURES.glob("clean.*")))
        self.assertEqual((code, out), (0, ""))

    def test_hits_exit_one(self):
        path = FIXTURES / "hits.sh"
        code, out, _ = self.run_main(path)
        self.assertEqual(code, 1)
        first = out.splitlines()[0]
        col = path.read_text().splitlines()[1].index("serves") + 1
        message = next(r.message for r in RULES if r.id == "copula-dodge")
        self.assertEqual(
            first, f"{path}:2:{col}: copula-dodge: {message}: serves as the"
        )

    def test_per_file_ignores(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_config(tmp, '[per-file-ignores]\n"docs/*" = ["ai-vocabulary"]\n')
            (root / "docs").mkdir()
            for name in ("docs/a.md", "b.md"):
                (root / name).write_text("a pivotal step\n")
            cwd = os.getcwd()
            os.chdir(root)
            try:
                code, out, _ = self.run_main("docs/a.md", root / "b.md")
            finally:
                os.chdir(cwd)
        self.assertEqual(code, 1)
        self.assertEqual(
            [line.split(":")[0] for line in out.splitlines()], [str(root / "b.md")]
        )

    def test_python_declared_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.py"
            path.write_bytes(b"# -*- coding: latin-1 -*-\n# caf\xe9: a pivotal step\n")
            code, out, _ = self.run_main(path)
        self.assertEqual(code, 1)
        self.assertIn(": ai-vocabulary: ", out)

    def test_suffix_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in (
                ("a.tsx", "// pivotal\n"),
                ("a.yml", "# pivotal\n"),
                ("a.h", "/* pivotal */\n"),
            ):
                with self.subTest(name):
                    path = Path(tmp) / name
                    path.write_text(text)
                    code, out, _ = self.run_main(path)
                    self.assertEqual(code, 1)
                    self.assertIn(": ai-vocabulary: ", out)

    def test_unsupported_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.txt"
            path.write_text("pivotal\n")
            code, out, err = self.run_main(path)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("unsupported file type", err)

    def write_config(self, directory, text):
        path = Path(directory) / ".ai-tells-lint.toml"
        path.write_text(text)
        return path

    def test_config_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.write_config(tmp, 'select = ["em-dash"]\n')
            code, out, _ = self.run_main("--config", config, FIXTURES / "hits.sh")
        self.assertEqual(code, 1)
        self.assertEqual(
            [line.split(": ")[1] for line in out.splitlines()], ["em-dash"]
        )

    def test_config_found_in_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_config(tmp, 'ignore = ["copula-dodge", "ai-vocabulary"]\n')
            sub = Path(tmp) / "sub"
            sub.mkdir()
            cwd = os.getcwd()
            os.chdir(sub)
            try:
                code, out, _ = self.run_main(FIXTURES / "hits.sh")
            finally:
                os.chdir(cwd)
        self.assertEqual(code, 1)
        self.assertEqual(
            [line.split(": ")[1] for line in out.splitlines()], ["em-dash"]
        )

    def test_bad_config_exit_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            for text in ('ignore = ["em-dahs"]\n', "ignore = [\n"):
                with self.subTest(text):
                    config = self.write_config(tmp, text)
                    code, out, err = self.run_main(
                        "--config", config, FIXTURES / "hits.sh"
                    )
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn(str(config), err)

    def test_missing_config_exit_two(self):
        code, out, err = self.run_main("--config", HERE / "missing.toml", "x.md")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("missing.toml", err)


if __name__ == "__main__":
    unittest.main()
