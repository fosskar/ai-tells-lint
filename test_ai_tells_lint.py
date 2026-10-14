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
        (6, "negative-parallelism", "not just"),
        (7, "em-dash", "—"),
        (8, "chatbot-phrase", "I hope"),
        (10, "markup-artefact", "utm_source=chatgpt.com"),
    ],
    "hits.nix": [
        (1, "copula-dodge", "serves as the"),
        (3, "ai-vocabulary", "pivotal"),
        (4, "em-dash", "—"),
        (5, "negative-parallelism", "not just"),
    ],
    "hits.sh": [
        (2, "copula-dodge", "serves as the"),
        (3, "ai-vocabulary", "pivotal"),
        (3, "em-dash", "—"),
    ],
    "hits.py": [
        (1, "copula-dodge", "serves as the"),
        (2, "ai-vocabulary", "pivotal"),
        (2, "em-dash", "—"),
        (3, "negative-parallelism", "not just"),
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

    def test_unsupported_suffix(self):
        code, out, err = self.run_main(HERE / "rules.toml")
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
