"""Marking findings as intended (baghban.config): --ignore and baghban.toml.

Prompted by neurogears/vestibular-vr#137: a demo that rewrites one scratch file
per run wants Overwrite=True, and its maintainers need a way to say so once.
"""

import json

import pytest

import baghban
from baghban.cli import main
from baghban.config import ConfigError, IgnoreRule, find_config, parse_ignore, read_config
from xmlkit import csv_writer, document, expr, include_expr, select_many, timer, workflow


def overwrite(fname="responses.csv", in_loop=False):
    if in_loop:
        inner = workflow(expr(("WorkflowInput", "<Name>Source1</Name>")),
                         expr(csv_writer(fname, overwrite=True)), edges=[(0, 1)])
        return document(workflow(expr(timer()), expr(select_many(inner)), edges=[(0, 1)]))
    return document(workflow(expr(timer()), expr(csv_writer(fname, overwrite=True)),
                             edges=[(0, 1)]))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ------------------------------------------------------------------ rules

def test_parse_ignore():
    assert parse_ignore("SILENT_OVERWRITE").pattern is None
    rule = parse_ignore("SILENT_OVERWRITE:demos/*")
    assert (rule.code, rule.pattern, rule.source) == ("SILENT_OVERWRITE", "demos/*", "--ignore")


@pytest.mark.parametrize("text,why", [
    ("SILENT_OVERWRIT", "unknown finding code"),  # a typo must not silently do nothing
    ("SILENT_OVERWRITE:", "CODE or CODE:PATTERN"),
    ("", "CODE or CODE:PATTERN"),
])
def test_bad_rules(text, why):
    with pytest.raises(ConfigError, match=why):
        parse_ignore(text)


def test_ignored_findings_are_listed_not_hidden(tmp_path):
    doc = baghban.load(write(tmp_path / "GNGTemplate.bonsai", overwrite()))
    report = baghban.check(doc, ignore=["SILENT_OVERWRITE"])
    assert report.findings == [] and report.exit_code(strict=True) == 0
    [(f, rule)] = report.ignored
    assert f.code == "SILENT_OVERWRITE" and rule.source == "--ignore"
    text = report.summary()
    assert "No findings" in text and "1 finding(s) marked as intended" in text
    assert report.to_dict()["ignored"][0]["ignored_by"] == "SILENT_OVERWRITE (--ignore)"


def test_a_rule_only_marks_its_own_code_and_files(tmp_path):
    demo = baghban.load(write(tmp_path / "demos" / "a.bonsai", overwrite()))
    rig = baghban.load(write(tmp_path / "rig" / "a.bonsai", overwrite()))
    rules = [parse_ignore("SILENT_OVERWRITE:demos/*", base=tmp_path)]
    assert baghban.check(demo, ignore=rules).findings == []
    assert baghban.check(rig, ignore=rules).codes() == ["SILENT_OVERWRITE"]
    assert baghban.check(demo, ignore=["DUPLICATE_OUTPUT"]).codes() == ["SILENT_OVERWRITE"]


def test_a_module_finding_can_be_marked_in_the_module(tmp_path):
    write(tmp_path / "modules" / "Log.bonsai", document(workflow(
        expr(("WorkflowInput", "<Name>Source1</Name>")), expr(csv_writer("log.csv", overwrite=True)),
        edges=[(0, 1)])))
    top = write(tmp_path / "main.bonsai", document(workflow(expr(timer()),
                                                            include_expr("modules/Log.bonsai"),
                                                            edges=[(0, 1)])))
    report = baghban.check(baghban.load(top),
                           ignore=[parse_ignore("SILENT_OVERWRITE:modules/Log.bonsai",
                                                base=tmp_path)])
    assert report.findings == [] and len(report.ignored) == 1


def test_ignoring_does_not_change_other_findings(tmp_path):
    doc = baghban.load(write(tmp_path / "w.bonsai", overwrite(in_loop=True)))
    report = baghban.check(doc, ignore=["DISABLED_WRITER"])
    assert [(f.code, f.severity) for f in report.findings] == [("SILENT_OVERWRITE", "error")]


# ------------------------------------------------------------------ configuration files

def test_find_config_walks_up_and_stops_at_the_repository(tmp_path):
    wf = write(tmp_path / "repo" / "src" / "Workflows" / "a.bonsai", overwrite())
    (tmp_path / "repo" / ".git").mkdir()
    assert find_config(wf) is None
    write(tmp_path / "baghban.toml", 'ignore = ["SILENT_OVERWRITE"]\n')  # outside the repo
    assert find_config(wf) is None
    write(tmp_path / "repo" / "pyproject.toml", '[project]\nname = "x"\n')  # no [tool.baghban]
    assert find_config(wf) is None
    write(tmp_path / "repo" / "pyproject.toml", '[tool.baghban]\nignore = ["DISABLED_WRITER"]\n')
    assert find_config(wf) == (tmp_path / "repo" / "pyproject.toml").resolve()
    write(tmp_path / "repo" / "src" / "baghban.toml", 'ignore = []\n')
    assert find_config(wf) == (tmp_path / "repo" / "src" / "baghban.toml").resolve()


def test_read_config(tmp_path):
    cfg = write(tmp_path / "baghban.toml",
                'ignore = ["APPENDS_ACROSS_RUNS"]\n\n[per-file-ignores]\n'
                '"src/Workflows/GNGTemplate.bonsai" = ["SILENT_OVERWRITE"]\n'
                '"docs/*" = "DANGLING_SUBJECT"\n')
    rules = read_config(cfg)
    assert [(r.code, r.pattern) for r in rules] == [
        ("APPENDS_ACROSS_RUNS", None), ("SILENT_OVERWRITE", "src/Workflows/GNGTemplate.bonsai"),
        ("DANGLING_SUBJECT", "docs/*")]
    assert all(r.base == tmp_path and r.source == "baghban.toml" for r in rules)
    py = write(tmp_path / "p" / "pyproject.toml",
               '[tool.baghban.per-file-ignores]\n"demo.bonsai" = ["SILENT_OVERWRITE"]\n')
    assert [(r.code, r.source) for r in read_config(py)] == [("SILENT_OVERWRITE", "pyproject.toml")]


@pytest.mark.parametrize("text,why", [
    ('ignore = ["NOPE"]\n', "unknown finding code 'NOPE'"),
    ('ignores = ["SILENT_OVERWRITE"]\n', "unknown setting"),
    ('ignore = "SILENT_OVERWRITE"\n', "must be a list"),
    ('[per-file-ignores]\n"a" = [1]\n', "must be a list of codes"),
    ('ignore = [\n', "baghban.toml"),  # not TOML
])
def test_bad_config(tmp_path, text, why):
    with pytest.raises(ConfigError, match=why):
        read_config(write(tmp_path / "baghban.toml", text))


# ------------------------------------------------------------------ command line

def test_cli_reads_baghban_toml(tmp_path, capsys):
    (tmp_path / ".git").mkdir()
    rig = write(tmp_path / "src" / "Workflows" / "trial.bonsai", overwrite("trial.csv", in_loop=True))
    demo = write(tmp_path / "src" / "Workflows" / "GNGTemplate.bonsai", overwrite())
    assert main(["check", str(rig)]) == 1
    assert main(["check", str(demo), "--strict"]) == 1  # a warning, until marked
    write(tmp_path / "baghban.toml", '[per-file-ignores]\n"src/Workflows/GNGTemplate.bonsai" = '
                                     '["SILENT_OVERWRITE"]\n"src/Workflows/trial.bonsai" = '
                                     '["SILENT_OVERWRITE"]\n')
    capsys.readouterr()
    assert main(["check", str(demo), "--strict"]) == 0
    assert "marked as intended" in capsys.readouterr().out
    assert main(["check", str(rig)]) == 0
    assert main(["check", str(rig), "--no-config"]) == 1
    capsys.readouterr()
    assert main(["check", str(rig), "--no-config", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["reports"][0]["ignored"] == []


def test_cli_ignore_option_and_errors(tmp_path, capsys):
    rig = write(tmp_path / "trial.bonsai", overwrite("trial.csv", in_loop=True))
    assert main(["check", str(rig), "--ignore", "SILENT_OVERWRITE"]) == 0
    assert main(["check", str(rig), "--ignore", "SILENT_OVERWRITE:other/*"]) == 1
    out = tmp_path / "trial.html"
    assert main(["render", str(rig), "-o", str(out), "--ignore", "SILENT_OVERWRITE"]) == 0
    with pytest.raises(SystemExit, match="unknown finding code"):
        main(["check", str(rig), "--ignore", "SILENT_OVERWRIT"])
    write(tmp_path / "baghban.toml", 'ignore = ["NOPE"]\n')
    with pytest.raises(SystemExit, match="unknown finding code 'NOPE'"):
        main(["check", str(rig)])
    capsys.readouterr()


def test_python_310_without_tomli_says_what_to_install(tmp_path, monkeypatch):
    import builtins
    real = builtins.__import__

    def no_toml(name, *args, **kwargs):
        if name in ("tomllib", "tomli"):
            raise ModuleNotFoundError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_toml)
    with pytest.raises(ConfigError, match="pip install tomli"):
        read_config(write(tmp_path / "baghban.toml", 'ignore = []\n'))
    # --ignore needs no file, so it works everywhere
    assert parse_ignore("SILENT_OVERWRITE").code == "SILENT_OVERWRITE"
