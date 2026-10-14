"""Flag LLM writing tells in markdown prose and in code comments.

usage: ai-tells-lint [--config PATH] FILE...

Prints `path:line:col: rule-id: message: match` per hit. Exits 1 on any hit
and 2 when a file cannot be read or scanned or the configuration is invalid.
Without --config, reads .ai-tells-lint.toml from the working directory or its
nearest parent that has one.
"""

import argparse
import bisect
import dataclasses
import fnmatch
import functools
import io
import os
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

import tomllib

RULES_PATH = Path(__file__).with_name("rules.toml")
CONFIG_NAME = ".ai-tells-lint.toml"
RULE_KINDS = ("words", "phrases", "regex")
RULE_KEYS = {"id", "message", "source", "raw", "examples", "min-hits", *RULE_KINDS}
CONFIG_KEYS = {
    "select",
    "ignore",
    "extend",
    "allow",
    "min-hits",
    "per-file-ignores",
    "rule",
}
RULE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_ID = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SUPPRESS = re.compile(
    rf"ai-tells-lint:[ \t]*(allow-next-line|allow|off|on)\b"
    rf"((?:[ \t]+{_ID})(?:[ \t]*,[ \t]*{_ID})*)?"
)

# BREAK replaces text outside the scanned region; nothing may match across it.
# MASK replaces code spans, quotes and URLs inside prose; a sentence-level
# regex may run across it, but words and phrases cannot match inside it.
BREAK = "\x01"
MASK = "\x00"

SEGMENT_SEP = re.compile(r"\n[ \t]*\n|" + BREAK + "+")

INLINE_MASKS = [
    re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL),
    re.compile(r"\]\([^)]*\)"),
    re.compile(r"^[ \t]*\[[^\]\n]+\]:[ \t]*\S+", re.MULTILINE),
    re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE),
    re.compile(r"\bwww\.\S+", re.IGNORECASE),
    re.compile(r"</?[a-z!][^<>]*>", re.IGNORECASE),
    re.compile(r'"[^"]*"'),
]

MD_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
MD_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
SH_HEREDOC = re.compile(r"<<(-?)[ \t]*\\?(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
SH_WORD_START = " \t\n;|&()<>"
C_COMMENT_STAR = re.compile(r"\n[ \t]*(\*+)(?!/)")
# a slash after one of these starts a js regex literal, not a division
JS_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
RS_RAW_STRING = re.compile(r'b?r(#*)"')
YAML_BLOCK_HEADER = re.compile(r"[|>][-+0-9]*[ \t]*(#[^\n]*)?(?=\n|\Z)")


class ScanError(Exception):
    pass


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Rule:
    id: str
    message: str
    kind: str
    items: tuple
    pattern: re.Pattern
    raw: bool
    examples: tuple
    min_hits: int = 1


@dataclass(frozen=True, order=True)
class Hit:
    line: int
    col: int
    rule: str
    message: str
    text: str


def _literal(s):
    return re.escape(s).replace("'", "['\u2019]")


def _bounded(body, first, last):
    left = r"(?<![\w./-])" if re.match(r"\w", first) else ""
    right = r"(?![\w/-]|\.\w)" if re.match(r"\w", last) else ""
    return left + body + right


def _compile(kind, items):
    if kind == "regex":
        return re.compile("|".join(f"(?:{r})" for r in items), re.IGNORECASE)
    items = sorted(items, key=len, reverse=True)
    if kind == "words":
        alts = [_bounded(_literal(w), w[0], w[-1]) for w in items]
    else:
        alts = [
            _bounded(r"\s+".join(_literal(t) for t in p.split()), p[0], p[-1])
            for p in items
        ]
    return re.compile("|".join(alts), re.IGNORECASE)


def _strings(value, what, allow_empty=True):
    if (
        not isinstance(value, list)
        or not all(isinstance(v, str) and v for v in value)
        or not (value or allow_empty)
    ):
        raise ConfigError(f"{what}: expected a list of non-empty strings")
    return value


def _table(value, what):
    if not isinstance(value, dict):
        raise ConfigError(f"{what}: expected a table")
    return value


def _rule(entry, what):
    entry = _table(entry, what)
    rule_id = entry.get("id")
    if not isinstance(rule_id, str) or not RULE_ID.match(rule_id):
        raise ConfigError(f"{what}: id {rule_id!r} must be lowercase words joined by -")
    what = f"rule {rule_id}"
    if unknown := sorted(entry.keys() - RULE_KEYS):
        raise ConfigError(f"{what}: unknown keys {unknown}")
    if not isinstance(entry.get("message"), str) or not entry["message"]:
        raise ConfigError(f"{what}: needs a non-empty message")
    kinds = [k for k in RULE_KINDS if k in entry]
    if len(kinds) != 1:
        raise ConfigError(f"{what}: needs exactly one of {', '.join(RULE_KINDS)}")
    kind = kinds[0]
    items = _strings(entry[kind], f"{what}: {kind}", allow_empty=False)
    raw = entry.get("raw", False)
    if not isinstance(raw, bool):
        raise ConfigError(f"{what}: raw must be true or false")
    examples = _strings(entry.get("examples", []), f"{what}: examples")
    min_hits = _min_hits(entry.get("min-hits", 1), f"{what}: min-hits")
    return _make_rule(rule_id, entry["message"], kind, items, raw, examples, min_hits)


def _min_hits(value, what):
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{what}: expected an integer of at least 1")
    return value


def _make_rule(rule_id, message, kind, items, raw, examples, min_hits=1):
    try:
        pattern = _compile(kind, items)
    except re.error as e:
        raise ConfigError(f"rule {rule_id}: bad regex: {e}") from e
    return Rule(
        id=rule_id,
        message=message,
        kind=kind,
        items=tuple(items),
        pattern=pattern,
        raw=raw,
        examples=tuple(examples),
        min_hits=min_hits,
    )


def load_rules(path=RULES_PATH):
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return [_rule(entry, f"{path}: rule") for entry in data["rule"]]


def find_config(start):
    for directory in (start, *start.parents):
        if (directory / CONFIG_NAME).is_file():
            return directory / CONFIG_NAME
    return None


def load_config(path):
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(str(e)) from e


def configure(rules, config):
    """Apply a parsed .ai-tells-lint.toml to the built-in rules."""
    if unknown := sorted(config.keys() - CONFIG_KEYS):
        raise ConfigError(f"unknown keys {unknown}; expected {sorted(CONFIG_KEYS)}")
    custom = config.get("rule", [])
    if not isinstance(custom, list):
        raise ConfigError("rule: expected an array of tables ([[rule]])")
    rules = rules + [_rule(entry, "rule") for entry in custom]
    by_id = {}
    for rule in rules:
        if rule.id in by_id:
            raise ConfigError(f"rule {rule.id}: duplicate rule id")
        by_id[rule.id] = rule

    all_ids = set(by_id)

    def known(rule_id, what):
        if rule_id not in all_ids:
            raise ConfigError(f"{what}: unknown rule id {rule_id!r}")
        return by_id.get(rule_id)

    extend = _table(config.get("extend", {}), "extend")
    allow = _table(config.get("allow", {}), "allow")
    for rule_id in extend.keys() | allow.keys():
        rule = known(rule_id, "extend" if rule_id in extend else "allow")
        if rule.kind == "regex":
            raise ConfigError(
                f"rule {rule_id}: is a regex rule; extend and allow take only"
                " words and phrases rules"
            )
        added = _strings(extend.get(rule_id, []), f"extend.{rule_id}")
        allowed = _strings(allow.get(rule_id, []), f"allow.{rule_id}")
        present = {i.casefold() for i in rule.items}
        if missing := [a for a in allowed if a.casefold() not in present]:
            raise ConfigError(f"allow.{rule_id}: not in the rule: {missing}")
        drop = {a.casefold() for a in allowed}
        items = [i for i in (*rule.items, *added) if i.casefold() not in drop]
        if items:
            by_id[rule_id] = _make_rule(
                rule.id,
                rule.message,
                rule.kind,
                items,
                rule.raw,
                rule.examples,
                rule.min_hits,
            )
        else:
            del by_id[rule_id]

    for rule_id, value in _table(config.get("min-hits", {}), "min-hits").items():
        rule = known(rule_id, "min-hits")
        min_hits = _min_hits(value, f"min-hits.{rule_id}")
        if rule:
            by_id[rule_id] = dataclasses.replace(rule, min_hits=min_hits)

    per_file = _table(config.get("per-file-ignores", {}), "per-file-ignores")
    for pattern, ids in per_file.items():
        for rule_id in _strings(ids, f"per-file-ignores.{pattern}"):
            known(rule_id, f"per-file-ignores.{pattern}")

    selected = by_id.keys()
    if "select" in config:
        selected = _strings(config["select"], "select")
        for rule_id in selected:
            known(rule_id, "select")
    ignored = _strings(config.get("ignore", []), "ignore")
    for rule_id in ignored:
        known(rule_id, "ignore")
    return [
        by_id[r.id]
        for r in rules
        if r.id in by_id and r.id in selected and r.id not in ignored
    ]


class Region:
    """A same-length copy of the text where everything outside the scanned
    region is BREAK, so offsets map straight back to line and column."""

    def __init__(self, text, keep_all):
        self.text = text
        self.chars = list(text) if keep_all else [_break(c) for c in text]
        # spans of text that may hold suppression markers; None: the region
        self.marker_spans = None

    def keep(self, start, end):
        self.chars[start:end] = self.text[start:end]

    def drop(self, start, end):
        self.chars[start:end] = [_break(c) for c in self.text[start:end]]

    def blank(self, start, end):
        self.chars[start:end] = " " * len(self.text[start:end])

    def __str__(self):
        return "".join(self.chars)


def _break(c):
    return c if c.isspace() else BREAK


def _line_comment(text, region, i):
    end = text.find("\n", i)
    end = len(text) if end < 0 else end
    region.blank(i, i + 1)
    region.keep(i + 1, end)
    return end


def scan_md(text):
    region = Region(text, keep_all=True)
    fence = None
    pos = 0
    for line in text.split("\n"):
        end = pos + len(line)
        m = MD_FENCE.match(line)
        if fence:
            region.drop(pos, end)
            if (
                m
                and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= len(fence)
                and not m.group(2).strip()
            ):
                fence = None
        elif m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            region.drop(pos, end)
            fence = m.group(1)
        pos = end + 1
    # markers count only in html comments outside fenced and inline code
    unfenced = str(region)
    in_code = [m.span() for m in INLINE_MASKS[0].finditer(unfenced)]
    region.marker_spans = [
        m.span()
        for m in MD_HTML_COMMENT.finditer(text)
        if unfenced[m.start()] != BREAK
        and not any(s <= m.start() < e for s, e in in_code)
    ]
    for m in MD_HTML_COMMENT.finditer(text):
        region.drop(m.start(), m.end())
    return region


def scan_nix(text):
    region = Region(text, keep_all=False)
    n = len(text)
    # each frame is "str", "istr", or a code frame holding its open-brace depth
    stack = [0]
    i = 0
    while i < n:
        top = stack[-1]
        c = text[i]
        if top == "str":
            if c == "\\":
                i += 2
            elif c == '"':
                stack.pop()
                i += 1
            elif text.startswith("$$", i):
                i += 2
            elif text.startswith("${", i):
                stack.append(0)
                i += 2
            else:
                i += 1
        elif top == "istr":
            if text.startswith("'''", i) or text.startswith("''$", i):
                i += 3
            elif text.startswith("''\\", i):
                i += 4
            elif text.startswith("''", i):
                stack.pop()
                i += 2
            elif text.startswith("$$", i):
                i += 2
            elif text.startswith("${", i):
                stack.append(0)
                i += 2
            else:
                i += 1
        elif c == "#":
            i = _line_comment(text, region, i)
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end
            region.blank(i, i + 2)
            region.keep(i + 2, end)
            region.blank(end, end + 2)
            i = end + 2
        elif c == '"':
            stack.append("str")
            i += 1
        elif text.startswith("''", i):
            stack.append("istr")
            i += 2
        elif c.isalpha() or c == "_":
            i += 1
            while i < n and (text[i].isalnum() or text[i] in "_'-"):
                i += 1
        elif c == "{":
            stack[-1] += 1
            i += 1
        elif c == "}":
            if top == 0 and len(stack) > 1:
                stack.pop()
            else:
                stack[-1] -= 1
            i += 1
        else:
            i += 1
    return region


def _skip_quoted(text, i, quote):
    n = len(text)
    i += 1
    while i < n and text[i] != quote:
        i += 2 if text[i] == "\\" else 1
    return i + 1


def scan_sh(text):
    region = Region(text, keep_all=False)
    n = len(text)
    i = text.find("\n") if text.startswith("#!") else 0
    i = n if i < 0 else i
    heredocs = []
    while i < n:
        c = text[i]
        if c == "\n":
            i += 1
            for delim, strip in heredocs:
                while i < n:
                    end = text.find("\n", i)
                    end = n if end < 0 else end
                    line = text[i:end]
                    i = end + 1
                    if (line.lstrip("\t") if strip else line) == delim:
                        break
            heredocs = []
        elif c == "\\":
            i += 2
        elif c == "'":
            i = text.find("'", i + 1)
            i = n if i < 0 else i + 1
        elif c in '"`':
            i = _skip_quoted(text, i, c)
        elif text.startswith("$'", i):
            i = _skip_quoted(text, i + 1, "'")
        elif text.startswith("${", i):
            depth = 0
            i += 1
            while i < n:
                depth += {"{": 1, "}": -1}.get(text[i], 0)
                i += 1
                if depth == 0:
                    break
        elif text.startswith("$#", i):
            i += 2
        elif c == "#" and (i == 0 or text[i - 1] in SH_WORD_START):
            i = _line_comment(text, region, i)
        elif text.startswith("<<<", i):
            i += 3
        elif m := SH_HEREDOC.match(text, i):
            heredocs.append((m.group(3), m.group(1) == "-"))
            i = m.end()
        else:
            i += 1
    return region


def scan_py(text):
    region = Region(text, keep_all=False)
    starts = [0]
    for line in text.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError) as e:
        raise ScanError(f"cannot tokenize: {e}") from e
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        (row, col) = tok.start
        if row == 1 and tok.string.startswith("#!"):
            continue
        start = starts[row - 1] + col
        _line_comment(text, region, start)
    return region


def _c_line_comment(text, region, i):
    end = text.find("\n", i)
    end = len(text) if end < 0 else end
    # doc comment markers: ///, //!
    j = i + 2
    while j < end and text[j] in "/!":
        j += 1
    region.blank(i, j)
    region.keep(j, end)
    return end


def _c_block_comment(text, region, i, nest):
    n = len(text)
    depth = 1
    j = i + 2
    while j < n and depth:
        if nest and text.startswith("/*", j):
            depth += 1
            j += 2
        elif text.startswith("*/", j):
            depth -= 1
            j += 2
        else:
            j += 1
    end = j - 2 if depth == 0 else n
    region.blank(i, i + 2)
    region.keep(i + 2, end)
    region.blank(end, j)
    # leading * of doc comment lines would split phrases across lines
    for m in C_COMMENT_STAR.finditer(text, i + 2, end):
        region.blank(m.start(1), m.end(1))
    return j


def _c_char(text, i):
    """Skip a char literal; a lone quote (a rust lifetime) is skipped alone."""
    if text.startswith("\\", i + 1):
        close = text.find("'", i + 3)
        return len(text) if close < 0 else close + 1
    if text.startswith("'", i + 2):
        return i + 3
    return i + 1


def _js_regex(text, i):
    """Skip a regex literal; returns i + 1 when the slash is not one."""
    in_class = False
    j = i + 1
    while j < len(text) and text[j] != "\n":
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if in_class:
            in_class = c != "]"
        elif c == "[":
            in_class = True
        elif c == "/":
            return j + 1
        j += 1
    return i + 1


def scan_c(text, lang):
    """Comments of C-like languages: go, rs, c, java and js (also ts, jsx, tsx)."""
    region = Region(text, keep_all=False)
    n = len(text)
    # each frame is "tmpl" (js template literal) or a code frame holding its
    # open-brace depth
    stack = [0]
    last = ""
    i = 0
    while i < n:
        c = text[i]
        if stack[-1] == "tmpl":
            if c == "\\":
                i += 2
            elif c == "`":
                stack.pop()
                last = "`"
                i += 1
            elif text.startswith("${", i):
                stack.append(0)
                i += 2
            else:
                i += 1
            continue
        if text.startswith("//", i):
            i = _c_line_comment(text, region, i)
        elif text.startswith("/*", i):
            i = _c_block_comment(text, region, i, nest=lang == "rs")
        elif c == "/" and lang == "js" and (not last or last in JS_REGEX_AFTER):
            i = _js_regex(text, i)
            last = "/"
        elif lang == "java" and text.startswith('"""', i):
            end = text.find('"""', i + 3)
            i = n if end < 0 else end + 3
            last = '"'
        elif c == '"':
            i = _skip_quoted(text, i, '"')
            last = '"'
        elif c == "'":
            i = _skip_quoted(text, i, "'") if lang == "js" else _c_char(text, i)
            last = "'"
        elif c == "`" and lang == "js":
            stack.append("tmpl")
            i += 1
        elif c == "`" and lang == "go":
            end = text.find("`", i + 1)
            i = n if end < 0 else end + 1
            last = "`"
        elif (
            lang == "rs"
            and (m := RS_RAW_STRING.match(text, i))
            and not (i and (text[i - 1].isalnum() or text[i - 1] == "_"))
        ):
            close = '"' + m.group(1)
            end = text.find(close, m.end())
            i = n if end < 0 else end + len(close)
            last = '"'
        else:
            if c == "{":
                stack[-1] += 1
            elif c == "}":
                if stack[-1] == 0 and len(stack) > 1:
                    stack.pop()
                else:
                    stack[-1] -= 1
            if not c.isspace():
                last = c
            i += 1
    return region


def _yaml_scalar_start(text, i):
    before = text[text.rfind("\n", 0, i) + 1 : i].rstrip()
    return not before or before[-1] in ":-[{,?"


def scan_yaml(text):
    region = Region(text, keep_all=False)
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if c == "#" and (i == 0 or text[i - 1].isspace()):
            i = _line_comment(text, region, i)
        elif c == "'" and _yaml_scalar_start(text, i):
            # '' is an escaped quote inside a single-quoted scalar
            j = i + 1
            while j < n and not (text[j] == "'" and not text.startswith("''", j)):
                j += 2 if text.startswith("''", j) else 1
            i = j + 1
        elif c == '"' and _yaml_scalar_start(text, i):
            i = _skip_quoted(text, i, '"')
        elif (
            c in "|>"
            and _yaml_scalar_start(text, i)
            and (m := YAML_BLOCK_HEADER.match(text, i))
        ):
            if m.group(1):
                _line_comment(text, region, m.start(1))
            line_start = text.rfind("\n", 0, i) + 1
            indent = len(text[line_start:i]) - len(text[line_start:i].lstrip(" "))
            # the block's content is every following line indented deeper, and
            # blank lines between
            j = m.end()
            while j < n:
                end = text.find("\n", j + 1)
                end = n if end < 0 else end
                line = text[j + 1 : end]
                if line.strip() and len(line) - len(line.lstrip(" ")) <= indent:
                    break
                j = end
            i = j
        else:
            i += 1
    return region


def scan_toml(text):
    region = Region(text, keep_all=False)
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        if text.startswith('"""', i):
            j = i + 3
            while j < n and not text.startswith('"""', j):
                j += 2 if text[j] == "\\" else 1
            i = j + 3
        elif text.startswith("'''", i):
            end = text.find("'''", i + 3)
            i = n if end < 0 else end + 3
        elif c == '"':
            i = _skip_quoted(text, i, '"')
        elif c == "'":
            end = text.find("'", i + 1)
            i = n if end < 0 else end + 1
        elif c == "#":
            i = _line_comment(text, region, i)
        else:
            i += 1
    return region


SCANNERS = {
    "md": scan_md,
    "nix": scan_nix,
    "sh": scan_sh,
    "py": scan_py,
    "go": functools.partial(scan_c, lang="go"),
    "rs": functools.partial(scan_c, lang="rs"),
    "c": functools.partial(scan_c, lang="c"),
    "java": functools.partial(scan_c, lang="java"),
    "js": functools.partial(scan_c, lang="js"),
    "yaml": scan_yaml,
    "toml": scan_toml,
}

SUFFIXES = {
    **{kind: kind for kind in SCANNERS},
    "h": "c",
    "jsx": "js",
    "mjs": "js",
    "cjs": "js",
    "ts": "js",
    "tsx": "js",
    "mts": "js",
    "cts": "js",
    "yml": "yaml",
}


def _mask_inline(segment):
    chars = list(segment)
    for pattern in INLINE_MASKS:
        for m in pattern.finditer("".join(chars)):
            for k in range(m.start(), m.end()):
                if chars[k] != "\n":
                    chars[k] = MASK
    return "".join(chars)


def _segments(region):
    pos = 0
    for m in SEGMENT_SEP.finditer(region + BREAK):
        if m.start() > pos and not region[pos : m.start()].isspace():
            yield pos, m.start()
        pos = m.end()


def _suppressions(scanned, region, line_starts):
    """Map suppression markers to a function (line, rule id) -> bool."""
    spans, source = scanned.marker_spans, scanned.text
    if spans is None:
        spans, source = [(0, len(region))], region
    allowed = {}
    switches = []
    for start, end in spans:
        for m in SUPPRESS.finditer(source, start, end):
            line = bisect.bisect_right(line_starts, m.start())
            directive = m.group(1)
            ids = set(re.findall(_ID, m.group(2) or "")) or None
            if directive in ("allow", "allow-next-line"):
                target = line + (directive == "allow-next-line")
                current = allowed.get(target, set())
                allowed[target] = (
                    None if ids is None or current is None else current | ids
                )
            else:
                switches.append((line, directive == "off"))
    switches.sort()

    def suppressed(line, rule_id):
        if line in allowed and (allowed[line] is None or rule_id in allowed[line]):
            return True
        i = bisect.bisect_right(switches, (line, True))
        return i > 0 and switches[i - 1][1]

    return suppressed


def lint(text, kind, rules):
    scanned = SCANNERS[kind](text)
    region = str(scanned)
    segments = list(_segments(region))
    prose = list(region)
    for start, end in segments:
        prose[start:end] = _mask_inline(region[start:end])
    prose = "".join(prose)

    line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
    suppressed = _suppressions(scanned, region, line_starts)
    hits = set()
    for rule in rules:
        source = region if rule.raw else prose
        for start, end in segments:
            found = []
            for m in rule.pattern.finditer(source, start, end):
                line = bisect.bisect_right(line_starts, m.start())
                if suppressed(line, rule.id):
                    continue
                col = m.start() - line_starts[line - 1] + 1
                matched = " ".join(text[m.start() : m.end()].split())
                found.append(Hit(line, col, rule.id, rule.message, matched))
            if len(found) >= rule.min_hits:
                hits.update(found)
    return sorted(hits)


def _ignored_rules(name, per_file):
    paths = {
        Path(name).as_posix(),
        Path(os.path.relpath(os.path.abspath(name))).as_posix(),
    }
    return {
        rule_id
        for pattern, ids in per_file.items()
        if any(fnmatch.fnmatchcase(p, pattern) for p in paths)
        for rule_id in ids
    }


def main(argv):
    parser = argparse.ArgumentParser(
        prog="ai-tells-lint",
        description="Flag LLM writing tells in markdown prose and in code and"
        " config comments.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help=f"configuration file; default: nearest {CONFIG_NAME} upwards from"
        " the working directory",
    )
    parser.add_argument("files", nargs="*", metavar="FILE")
    args = parser.parse_args(argv)

    config_path = args.config or find_config(Path.cwd())
    try:
        config = load_config(config_path) if config_path else {}
        rules = configure(load_rules(), config)
    except ConfigError as e:
        print(f"ai-tells-lint: {config_path}: {e}", file=sys.stderr)
        return 2
    per_file = config.get("per-file-ignores", {})

    status = 0
    for name in args.files:
        kind = SUFFIXES.get(Path(name).suffix[1:])
        if kind is None:
            print(f"{name}: unsupported file type", file=sys.stderr)
            status = 2
            continue
        try:
            ignored = _ignored_rules(name, per_file)
            file_rules = [r for r in rules if r.id not in ignored]
            hits = lint(Path(name).read_text(encoding="utf-8"), kind, file_rules)
        except (OSError, UnicodeDecodeError, ScanError) as e:
            print(f"{name}: {e}", file=sys.stderr)
            status = 2
            continue
        for h in hits:
            print(f"{name}:{h.line}:{h.col}: {h.rule}: {h.message}: {h.text}")
        if hits and status == 0:
            status = 1
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
