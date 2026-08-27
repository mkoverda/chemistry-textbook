#!/usr/bin/env python3
"""
Проверки исходников.

    ./check.py              все проверки, полный отчёт
    ./check.py -q           только найденные проблемы
    ./check.py --list       перечислить проверки и выйти
    ./check.py --only A1,C3 выполнить только указанные

Код возврата: 0 — ошибок нет, 1 — есть ошибки, 2 — скрипт не смог работать.
Предупреждения на код возврата не влияют.
"""

import os
import re
import sys
import glob
import collections


ROOT_MARKER = "main.tex"

FIG_DIRS = ("figs", "tables")
SRC_FIG_DIRS = ("source_figs", "source_tables")

BUILD_DIR = "build"

FLOAT_SPECS = ("[htbp]", "[H]")

SIUNITX_BUILTINS = {
    "per", "squared", "cubed", "degree", "degreeCelsius", "percent",
    "of", "raiseto", "tothe", "highlight", "cancel",
}

LONG_LINE = 300

CYR = "А-Яа-яЁё"


ERROR, WARN, INFO = "ОШИБКА", "ВНИМАНИЕ", "СПРАВКА"

Finding = collections.namedtuple("Finding", "level file line text")

CHECKS = []


def check(code, title, level=ERROR):
    def wrap(fn):
        fn.code, fn.title, fn.level = code, title, level
        CHECKS.append(fn)
        return fn
    return wrap


class Project(object):

    def __init__(self, root):
        self.root = root
        self.files = sorted(
            os.path.basename(p) for p in glob.glob(os.path.join(root, "*.tex"))
        )
        self.raw = {}
        self.clean = {}
        for f in self.files:
            with open(os.path.join(root, f), encoding="utf-8") as fh:
                s = fh.read()
            self.raw[f] = s
            self.clean[f] = strip_comments(s)
        self.chapters = [f for f in self.files if f != "preamble.tex"]

    def line_of(self, f, pos):
        return self.raw[f].count("\n", 0, pos) + 1

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def build_file(self, name):
        p = self.path(BUILD_DIR, name)
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read()


def strip_comments(s):
    out = []
    for line in s.split("\n"):
        i, n = 0, len(line)
        cut = None
        while i < n:
            if line[i] == "\\":
                i += 2
                continue
            if line[i] == "%":
                cut = i
                break
            i += 1
        out.append(line if cut is None else line[:cut] + " " * (n - cut))
    return "\n".join(out)


def braced(s, i):
    if i >= len(s) or s[i] != "{":
        raise ValueError("ожидалась '{'")
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    raise ValueError("непарная скобка")


def strip_env(s, *cmds):
    out = list(s)
    for cmd in cmds:
        for m in re.finditer(r"\\" + cmd + r"(?=\{)", s):
            try:
                body, end = braced(s, m.end())
            except ValueError:
                continue
            for k in range(m.start(), end):
                if out[k] != "\n":
                    out[k] = " "
    return "".join(out)


def strip_math(s):
    out = list(s)
    for m in re.finditer(r"(?<!\\)\$(?:[^$\\]|\\.)*\$", s, re.S):
        for k in range(m.start(), m.end()):
            if out[k] != "\n":
                out[k] = " "
    return "".join(out)



def all_labels(p):
    found = collections.defaultdict(list)
    rules = (
        (re.compile(r"\\label\{([^}]*)\}"), ""),
        (re.compile(r"\\term\{(?:[^{}]|\{[^{}]*\})*\}\{([^}]*)\}"), "term:"),
        (re.compile(r"\\begin\{problem\}\{[^}]*\}\{([^}]*)\}"), "prob:"),
        (re.compile(r"\\begin\{example\}\{[^}]*\}\{([^}]*)\}"), "ex:"),
        (re.compile(r"\\reaction\[([^\]]+)\]"), ""),
    )
    for f in p.files:
        for pat, prefix in rules:
            for m in pat.finditer(p.clean[f]):
                found[prefix + m.group(1)].append((f, p.line_of(f, m.start())))
    return found



@check("A1", "Латиница внутри кириллического слова и наоборот")
def check_alphabet_mix(p):
    pat = re.compile("[A-Za-z][" + CYR + "]|[" + CYR + "][A-Za-z]")
    for f in p.files:
        s = strip_env(strip_math(p.clean[f]), "ce", "label", "ref", "eqref",
                      "hyperref", "index", "includegraphics", "input")
        for m in pat.finditer(s):
            ctx = p.raw[f][max(0, m.start() - 25):m.end() + 25].replace("\n", " ")
            yield Finding(ERROR, f, p.line_of(f, m.start()),
                          "смешение азбук: %r в «…%s…»" % (m.group(0), ctx))


@check("A2", "Короткое тире или дефис в математическом режиме")
def check_dash_in_math(p):
    for f in p.files:
        s = p.clean[f]
        for m in re.finditer(r"(?<!\\)\$(?:[^$\\]|\\.)*\$", s, re.S):
            body = m.group(0)
            for bad, what in (("\u2013", "короткое тире"),
                              ("\u2014", "длинное тире"),
                              ("\\textendash", "\\textendash"),
                              ("\\textemdash", "\\textemdash")):
                if bad in body:
                    yield Finding(ERROR, f, p.line_of(f, m.start()),
                                  "%s внутри $…$: %s" % (what, body[:60]))


@check("A3", "Пробел между \\begin/\\end и скобкой")
def check_begin_space(p):
    """\\end {sol} работает, но ломает любой поиск по \\end{sol}."""
    for f in p.files:
        for m in re.finditer(r"\\(begin|end)[ \t]+\{", p.clean[f]):
            yield Finding(ERROR, f, p.line_of(f, m.start()),
                          "\\%s с пробелом перед скобкой" % m.group(1))


@check("A4", "Юникод вместо команд LaTeX")
def check_unicode(p):
    allowed = set("№©")
    bad = {
        "\u00ab": "« → <<", "\u00bb": "» → >>",
        "\u2013": "– → -- или ~---", "\u2014": "— → ~---",
        "\u2011": "‑ (неразрывный дефис) → \\nobreakdash-",
        "\u2026": "… → \\ldots",
    }
    ok = re.compile("[\u0400-\u04FF\\s\\x00-\\x7F]")
    for f in p.files:
        for i, ch in enumerate(p.clean[f]):
            if ok.match(ch) or ch in allowed:
                continue
            hint = bad.get(ch, "не-ASCII и не кириллица")
            yield Finding(ERROR, f, p.clean[f].count("\n", 0, i) + 1,
                          "U+%04X %s" % (ord(ch), hint))



@check("A5", "Не совпадает число \\begin и \\end")
def check_env_balance(p):
    for f in p.files:
        opened = collections.Counter(re.findall(r"\\begin\{([a-zA-Z*]+)\}", p.clean[f]))
        closed = collections.Counter(re.findall(r"\\end\{([a-zA-Z*]+)\}", p.clean[f]))
        for env in sorted(set(opened) | set(closed)):
            if opened[env] != closed[env] and env not in ("document",):
                yield Finding(ERROR, f, 0,
                              "%s: \\begin %d раз, \\end %d раз"
                              % (env, opened[env], closed[env]))



@check("B1", "Неизвестная команда внутри \\qty/\\unit")
def check_units(p):
    pre = p.clean.get("preamble.tex", "")
    declared = set(re.findall(r"\\DeclareSIUnit\\([a-zA-Z]+)", pre))
    if not declared:
        yield Finding(WARN, "preamble.tex", 0,
                      "не найдено ни одного \\DeclareSIUnit — проверка пропущена")
        return
    known = declared | SIUNITX_BUILTINS
    for f in p.chapters:
        s = p.clean[f]
        for m in re.finditer(r"\\(qty|unit)(?=\{)", s):
            try:
                first, end = braced(s, m.end())
                if m.group(1) == "qty":
                    arg, end = braced(s, end)
                else:
                    arg = first
            except ValueError:
                continue
            for cmd in re.findall(r"\\([a-zA-Z]+)", arg):
                if cmd not in known:
                    yield Finding(ERROR, f, p.line_of(f, m.start()),
                                  "\\%s внутри \\%s{…} — не объявлена в преамбуле"
                                  % (cmd, m.group(1)))


@check("B2", "Степень окисления вне математического режима", WARN)
def check_oxidation_state(p):
    word = re.compile("степен\\w* окислени\\w*", re.I)
    sign = re.compile("(?<![\\w$+\\-])([+\\-\\u2212])\\s?\\d")
    for f in p.chapters:
        s = strip_math(p.clean[f])
        seen = set()
        for m in word.finditer(s):
            d = sign.search(s[m.end():m.end() + 40])
            if not d:
                continue
            ln = p.line_of(f, m.start())
            if (ln, m.start()) in seen:
                continue
            seen.add((ln, m.start()))
            frag = re.sub(r"\\s+", " ",
                          p.raw[f][m.start():m.end() + d.end()]).strip()
            minus = d.group(1) != "+"
            yield Finding(ERROR if minus else WARN, f, ln,
                          "%s: «%s»" % ("минус набран дефисом" if minus
                                        else "знак вне $…$", frag))


@check("B3", "Пробел перед точкой внутри \\ce")
def check_ce_dot(p):
    for f in p.chapters:
        s = p.clean[f]
        for m in re.finditer(r"\\ce(?=\{)", s):
            try:
                body, _ = braced(s, m.end())
            except ValueError:
                continue
            cleaned = re.sub(r"\s*\((?:\^|v)\)\s*", "", body)
            if re.search(r"\s\{?\.", cleaned):
                yield Finding(ERROR, f, p.line_of(f, m.start()),
                              "пробел перед точкой в \\ce{%s}" % body[:50])



@check("C1", "Ссылка на формулу через \\ref вместо \\eqref")
def check_eqref(p):
    for f in p.chapters:
        s = p.clean[f]
        for m in re.finditer(r"\\ref\{(eq|ce):[^}]*\}", s):
            line_start = s.rfind("\n", 0, m.start()) + 1
            head = s[line_start:m.start()]
            open_paren = head.rfind("(")
            if open_paren >= 0 and ")" not in head[open_paren:]:
                continue
            yield Finding(ERROR, f, p.line_of(f, m.start()),
                          "%s — нужен \\eqref (или скобки вокруг)" % m.group(0))


@check("C2", "\\fbox вокруг формулы вместо \\boxed")
def check_boxed(p):
    for f in p.chapters:
        for m in re.finditer(r"\\fbox\s*\{\s*\$", p.clean[f]):
            yield Finding(ERROR, f, p.line_of(f, m.start()),
                          "\\fbox{$…$} — нужен \\boxed{…} из amsmath")


@check("C3", "Ручной отступ \\hspace*{\\parindent}")
def check_manual_indent(p):
    for f in p.chapters:
        for m in re.finditer(r"\\hspace\*?\{\\parindent\}", p.clean[f]):
            yield Finding(ERROR, f, p.line_of(f, m.start()),
                          "ручной отступ — за это отвечает indentfirst")


@check("C4", "Спецификатор плавающего объекта не [htbp] и не [H]")
def check_float_spec(p):
    for f in p.chapters:
        for m in re.finditer(r"\\begin\{(figure|table)\}(\[[^\]]*\])?", p.clean[f]):
            spec = m.group(2) or "(нет)"
            if spec not in FLOAT_SPECS:
                yield Finding(ERROR, f, p.line_of(f, m.start()),
                              "\\begin{%s}%s — ожидается %s"
                              % (m.group(1), spec, " или ".join(FLOAT_SPECS)))


@check("C5", "Плавающий объект без \\caption")
def check_float_caption(p):
    for f in p.chapters:
        if f == "appendix.tex":
            continue
        s = p.clean[f]
        for m in re.finditer(r"\\begin\{(figure|table)\}", s):
            env = m.group(1)
            end = s.find("\\end{" + env + "}", m.end())
            if end < 0:
                continue
            if "\\caption" not in s[m.end():end]:
                yield Finding(ERROR, f, p.line_of(f, m.start()),
                              "%s без \\caption — плавать незачем, нужен center" % env)


@check("C6", "Ширина рисунка задана числом там, где это ширина полосы", WARN)
def check_widths(p):
    for f in p.chapters:
        s = p.clean[f]
        for m in re.finditer(r"\\includegraphics\[([^\]]*)\]", s):
            w = re.search(r"width\s*=\s*([\d.]+)cm", m.group(1))
            if w and abs(float(w.group(1)) - 13.0) < 0.01:
                yield Finding(WARN, f, p.line_of(f, m.start()),
                              "width=%scm — это и есть \\linewidth" % w.group(1))


@check("C7", "Обёртка wrapfigure и картинка в разных единицах")
def check_wrapfig(p):
    """Два числа, которые обязаны согласовываться, должны мериться одинаково."""
    for f in p.chapters:
        s = p.clean[f]
        for m in re.finditer(
                r"\\begin\{wrapfigure\}(?:\[[^\]]*\])?\{[lrLR]\}\{([^}]*)\}", s):
            end = s.find("\\end{wrapfigure}", m.end())
            body = s[m.end():end if end > 0 else m.end()]
            img = re.search(r"width\s*=\s*([^,\]]+)", body)
            if not img:
                continue
            wrap_rel = "\\" in m.group(1)
            img_rel = "\\" in img.group(1)
            if wrap_rel and not img_rel:
                yield Finding(ERROR, f, p.line_of(f, m.start()),
                              "обёртка {%s} задана долей полосы, а картинка "
                              "width=%s — числом: при правке полей разъедутся"
                              % (m.group(1), img.group(1).strip()))
            elif not img_rel:
                yield Finding(WARN, f, p.line_of(f, m.start()),
                              "два числа вместо одного: обёртка {%s}, картинка "
                              "width=%s (проще width=\\linewidth)"
                              % (m.group(1), img.group(1).strip()))


@check("C8", "Триплет «термин + метка + указатель» мимо \\term")
def check_term_macro(p):
    for f in p.chapters:
        for m in re.finditer(r"\\textbf\{[^{}]*\}\\label\{term:", p.clean[f]):
            yield Finding(ERROR, f, p.line_of(f, m.start()),
                          "нужен \\term{текст}{ключ}{запись указателя}")



@check("C9", "У \\term не хватает третьего аргумента")
def check_term_arity(p):
    """\\term объявлен с двумя аргументами, третий читает сам — так же,
    как это делает \\index. Плата за это: если третью группу забыть,
    макрос молча съест то, что идёт следом.
    """
    for f in p.chapters:
        s = p.clean[f]
        for m in re.finditer(r"\\term(?=\{)", s):
            try:
                _, e1 = braced(s, m.end())
                _, e2 = braced(s, e1)
            except ValueError:
                yield Finding(ERROR, f, p.line_of(f, m.start()),
                              "\\term с неполными аргументами")
                continue
            rest = s[e2:e2 + 4].lstrip()
            if not rest.startswith("{"):
                yield Finding(ERROR, f, p.line_of(f, m.start()),
                              "\\term без третьего аргумента — съест текст следом")



@check("D1", "Запись указателя с математикой без ключа сортировки")
def check_index_sortkey(p):
    """xindy отбрасывает математику при вычислении ключа.

    Из-за этого $\\alpha$-частицы и $\\beta$-частицы получают одинаковый
    ключ «частицы», и одна из записей исчезает — молча, без единого
    предупреждения. Спасает явный ключ: альфа-частицы@$\\alpha$-частицы.
    """
    for f in p.files:
        s = p.clean[f]
        for m in re.finditer(r"\\index(?=\{)", s):
            try:
                body, _ = braced(s, m.end())
            except ValueError:
                continue
            if "$" in body and "@" not in body:
                yield Finding(ERROR, f, p.line_of(f, m.start()),
                              "\\index{%s} — добавьте ключ сортировки «ключ@%s»"
                              % (body, body))


@check("D2", "Разные записи указателя с одинаковым ключом сортировки")
def check_index_collision(p):
    """Две записи с одним ключом сливаются в одну."""
    seen = collections.defaultdict(list)
    for f in p.files:
        s = p.clean[f]
        for m in re.finditer(r"\\index(?=\{)", s):
            try:
                body, _ = braced(s, m.end())
            except ValueError:
                continue
            key = body.split("@")[0] if "@" in body else re.sub(r"\$[^$]*\$", "", body)
            seen[key.strip().lower()].append((f, p.line_of(f, m.start()), body))
    for key, items in sorted(seen.items()):
        forms = set(x[2] for x in items)
        if len(forms) > 1:
            f, ln, _ = items[0]
            yield Finding(ERROR, f, ln,
                          "ключ «%s» делят разные записи: %s"
                          % (key, ", ".join(sorted(forms))))



@check("E1", "Ключ задачи и ключ её решения не совпадают")
def check_problem_sol(p):
    """Номер ответа проставляется вручную: \\begin{sol}{\\ref{prob:ключ}}.

    Опечатка в ключе разрешится молча — просто не туда.
    """
    for f in p.chapters:
        t = re.sub(r"\\(begin|end)\s+\{", r"\\\1{", p.clean[f])
        for m in re.finditer(
                r"\\begin\{problem\}\{[^}]*\}\{([^}]*)\}(.*?)\\end\{problem\}",
                t, re.S):
            key, body = m.group(1), m.group(2)
            sols = re.findall(r"\\begin\{sol\}\{\\ref\{prob:([^}]*)\}\}", body)
            if not sols:
                yield Finding(WARN, f, p.line_of(f, m.start()),
                              "задача %s без блока sol" % key)
            for s in sols:
                if s != key:
                    yield Finding(ERROR, f, p.line_of(f, m.start()),
                                  "задача %s, а в решении \\ref{prob:%s}" % (key, s))


@check("E2", "\\includeonly не перечисляет все главы")
def check_includeonly(p):
    """Пока список полон, всё верно. Стоит закомментировать одну главу ради
    быстрой пересборки — и build/ans.tex тихо перезапишется без её ответов.
    """
    s = p.clean.get("main.tex", "")
    inc = re.findall(r"\\include\{([^}]*)\}", s)
    m = re.search(r"\\includeonly\{(.*?)\}", s, re.S)
    if not m:
        if inc:
            yield Finding(INFO, "main.tex", 0, "\\includeonly не используется")
        return
    only = [x.strip() for x in m.group(1).split(",") if x.strip()]
    for name in inc:
        if name not in only:
            yield Finding(ERROR, "main.tex", p.line_of("main.tex", m.start()),
                          "глава «%s» подключена, но выключена в \\includeonly" % name)



@check("F1", "Повторяющиеся метки")
def check_dup_labels(p):
    seen = all_labels(p)
    for key, places in sorted(seen.items()):
        if len(places) > 1:
            yield Finding(ERROR, places[0][0], places[0][1],
                          "метка «%s» объявлена %d раза: %s"
                          % (key, len(places),
                             ", ".join("%s:%d" % x for x in places[1:])))


@check("F2", "Ссылка на несуществующую метку")
def check_missing_labels(p):
    labels = set(all_labels(p))
    ref = re.compile(r"\\hyperref\[([^\]]*)\]|\\(?:eqref|ref|pageref)\{([^}]*)\}")
    for f in p.chapters:
        for m in ref.finditer(p.clean[f]):
            key = m.group(1) or m.group(2)
            if key and key not in labels:
                yield Finding(ERROR, f, p.line_of(f, m.start()),
                              "ссылка на несуществующую метку «%s»" % key)


@check("F3", "Рисунок подключён, а файла нет")
def check_missing_figures(p):
    for f in p.chapters:
        for m in re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}",
                             p.clean[f]):
            if not os.path.exists(p.path(m.group(1))):
                yield Finding(ERROR, f, p.line_of(f, m.start()),
                              "нет файла %s" % m.group(1))


@check("F4", "Файл рисунка есть, но нигде не используется", WARN)
def check_unused_figures(p):
    used = set()
    for f in p.chapters:
        used |= set(re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}",
                               p.clean[f]))
    for d in FIG_DIRS:
        base = p.path(d)
        if not os.path.isdir(base):
            continue
        for dirpath, _, names in os.walk(base):
            for n in names:
                if not n.lower().endswith(".pdf"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, n), p.root)
                if rel not in used:
                    yield Finding(WARN, rel, 0, "файл не используется ни в одной главе")


@check("F5", "У рисунка нет исходника", WARN)
def check_figure_sources(p):
    """Каждому figs/x/y.pdf должен отвечать source_figs/x/y.afdesign."""
    pairs = [("figs", "source_figs")]
    for out_dir, src_dir in pairs:
        base = p.path(out_dir)
        if not os.path.isdir(base) or not os.path.isdir(p.path(src_dir)):
            continue
        for dirpath, _, names in os.walk(base):
            for n in names:
                if not n.lower().endswith(".pdf"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, n), base)
                src = p.path(src_dir, os.path.splitext(rel)[0] + ".afdesign")
                if not os.path.exists(src):
                    yield Finding(WARN, os.path.join(out_dir, rel), 0,
                                  "нет исходника в %s/" % src_dir)



@check("G1", "Пробелы в конце строки", WARN)
def check_trailing_ws(p):
    for f in p.files:
        for i, line in enumerate(p.raw[f].split("\n"), 1):
            if line != line.rstrip() and line.strip():
                yield Finding(WARN, f, i, "пробелы в конце строки")


@check("G2", "Очень длинные строки", INFO)
def check_long_lines(p):
    """Абзац одной строкой — git diff превращается в «удалён, добавлен»."""
    n = 0
    longest = None
    for f in p.chapters:
        for i, line in enumerate(p.raw[f].split("\n"), 1):
            if len(line) > LONG_LINE:
                n += 1
                if longest is None or len(line) > longest[2]:
                    longest = (f, i, len(line))
    if n:
        yield Finding(INFO, longest[0], longest[1],
                      "строк длиннее %d символов: %d (самая длинная — %d)"
                      % (LONG_LINE, n, longest[2]))



@check("H1", "Ошибки и предупреждения последней сборки")
def check_log(p):
    log = p.build_file("main.log")
    if log is None:
        yield Finding(INFO, BUILD_DIR + "/main.log", 0,
                      "журнала нет — соберите проект, чтобы проверить и его")
        return
    if "Output written" not in log:
        yield Finding(WARN, BUILD_DIR + "/main.log", 0,
                      "журнал от незавершённой сборки — проверки по нему пропущены")
        return

    lines = log.split("\n")
    for i, line in enumerate(lines, 1):
        if line.startswith("!"):
            yield Finding(ERROR, BUILD_DIR + "/main.log", i, line.strip()[:120])

    counts = collections.OrderedDict((
        ("Warning", ERROR),
        ("Overfull \\hbox", ERROR),
        ("Overfull \\vbox", ERROR),
        ("Underfull \\hbox", INFO),
        ("Underfull \\vbox", INFO),
    ))
    for needle, level in counts.items():
        n = log.count(needle)
        if n:
            yield Finding(level, BUILD_DIR + "/main.log", 0, "%s: %d" % (needle, n))

    for needle in ("There were undefined references",
                   "multiply defined", "Label(s) may have changed"):
        if needle in log:
            yield Finding(ERROR, BUILD_DIR + "/main.log", 0, needle)


@check("H2", "Сводка по собранному документу", INFO)
def check_stats(p):
    idx, ind = p.build_file("main.idx"), p.build_file("main.ind")
    if idx is not None:
        yield Finding(INFO, BUILD_DIR + "/main.idx", 0,
                      "записей указателя: %d" % idx.count("\\indexentry"))
    if ind is not None:
        yield Finding(INFO, BUILD_DIR + "/main.ind", 0,
                      "ссылок в указателе: %d, групп букв: %d"
                      % (ind.count("\\hyperpage"), ind.count("\\lettergroup")))
    n_lab = sum(len(re.findall(r"\\label\{", p.clean[f])) for f in p.files)
    n_fig = sum(len(re.findall(r"\\includegraphics", p.clean[f])) for f in p.chapters)
    n_prob = sum(len(re.findall(r"\\begin\{problem\}", p.clean[f])) for f in p.chapters)
    yield Finding(INFO, "", 0,
                  "меток: %d, рисунков: %d, задач: %d, файлов .tex: %d"
                  % (n_lab, n_fig, n_prob, len(p.files)))



def find_root():
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (here, os.getcwd()):
        cur = d
        for _ in range(5):
            if os.path.exists(os.path.join(cur, ROOT_MARKER)):
                return cur
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    return None


class Palette(object):
    def __init__(self, on):
        self.red = "\033[31m" if on else ""
        self.yellow = "\033[33m" if on else ""
        self.grey = "\033[90m" if on else ""
        self.bold = "\033[1m" if on else ""
        self.off = "\033[0m" if on else ""

    def paint(self, level, text):
        return {ERROR: self.red, WARN: self.yellow, INFO: self.grey}[level] \
            + text + self.off


def main(argv):
    quiet = "-q" in argv or "--quiet" in argv
    if "--list" in argv:
        for fn in CHECKS:
            print("  %-4s %s  [%s]" % (fn.code, fn.title, fn.level))
        return 0

    only = None
    for i, a in enumerate(argv):
        raw = None
        if a.startswith("--only="):
            raw = a[len("--only="):]
        elif a == "--only" and i + 1 < len(argv):
            raw = argv[i + 1]
        if raw:
            only = set(x.strip().upper() for x in raw.split(",") if x.strip())
    if only:
        unknown = only - set(fn.code for fn in CHECKS)
        if unknown:
            sys.stderr.write("нет таких проверок: %s (см. --list)\n"
                             % ", ".join(sorted(unknown)))
            return 2

    root = find_root()
    if root is None:
        sys.stderr.write("не нашёл %s — запустите из папки проекта\n" % ROOT_MARKER)
        return 2

    c = Palette(sys.stdout.isatty() and os.environ.get("NO_COLOR") is None)
    p = Project(root)
    if not p.files:
        sys.stderr.write("в %s нет файлов .tex\n" % root)
        return 2

    print("%sПроверка проекта%s  %s" % (c.bold, c.off, root))
    print()

    totals = collections.Counter()
    for fn in CHECKS:
        if only and fn.code not in only:
            continue
        try:
            found = list(fn(p))
        except Exception as e:
            found = [Finding(ERROR, "", 0,
                             "проверка упала: %s: %s" % (type(e).__name__, e))]
        for x in found:
            totals[x.level] += 1

        if not found:
            if not quiet:
                print("  %s  %-4s %s" % (c.paint(INFO, "·"), fn.code, fn.title))
            continue

        worst = ERROR if any(x.level == ERROR for x in found) else \
            (WARN if any(x.level == WARN for x in found) else INFO)
        mark = {ERROR: "✗", WARN: "!", INFO: "i"}[worst]
        if quiet and worst == INFO:
            continue
        print("  %s  %-4s %s%s%s"
              % (c.paint(worst, mark), fn.code,
                 c.bold if worst == ERROR else "", fn.title, c.off))
        shown = found if len(found) <= 12 else found[:12]
        for x in shown:
            where = x.file if not x.line else "%s:%d" % (x.file, x.line)
            print("        %s %s" % (c.paint(x.level, where.ljust(44)), x.text))
        if len(found) > len(shown):
            print("        %s" % c.paint(INFO,
                  "… и ещё %d — покажет ./check.py --only=%s"
                  % (len(found) - len(shown), fn.code)))
        print()

    print()
    print("  %s   %s   %s"
          % (c.paint(ERROR, "ошибок: %d" % totals[ERROR]),
             c.paint(WARN, "предупреждений: %d" % totals[WARN]),
             c.paint(INFO, "справок: %d" % totals[INFO])))
    return 1 if totals[ERROR] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))