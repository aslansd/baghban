import json
from pathlib import Path

import baghban
from baghban.cli import main
from xmlkit import csv_writer, document, expr, publish, subscribe, timer, workflow

EXAMPLES = Path(__file__).parents[1] / "examples"
V1 = EXAMPLES / "rig_v1" / "foraging.bonsai"
V2 = EXAMPLES / "rig_v2" / "foraging.bonsai"


def load(xml):
    return baghban.loads(document(xml))


# ------------------------------------------------------------------ diff

def test_identical_after_reformatting():
    xml = workflow(expr(timer()), expr(csv_writer()), edges=[(0, 1)])
    squashed = document(xml)
    spaced = squashed.replace("><", ">\n    <")
    assert baghban.diff(baghban.loads(squashed), baghban.loads(spaced)).identical


def test_property_change():
    a = load(workflow(expr(timer("PT1S"))))
    b = load(workflow(expr(timer("PT2S"))))
    changes = baghban.diff(a, b).changes
    assert [(c.kind, c.path, c.detail, c.before, c.after) for c in changes] == \
        [("changed", "Timer", "Period", "PT1S", "PT2S")]


def test_inserting_an_unrelated_node_does_not_renumber():
    a = load(workflow(expr(timer()), expr(csv_writer("x.csv")), edges=[(0, 1)]))
    b = load(workflow(expr(publish("New")), expr(timer()), expr(csv_writer("x.csv")),
                      edges=[(1, 2)]))
    kinds = [(c.kind, c.path) for c in baghban.diff(a, b).changes]
    assert kinds == [("added", "PublishSubject:New")]


def test_rewired_edge():
    a = load(workflow(expr(timer()), expr(publish("A")), expr(subscribe("A")), edges=[(0, 1)]))
    b = load(workflow(expr(timer()), expr(publish("A")), expr(subscribe("A")), edges=[(2, 1)]))
    lines = [c.line() for c in baghban.diff(a, b).changes]
    assert "+ edge  /: SubscribeSubject:A -> PublishSubject:A (Source1)" in lines
    assert "- edge  /: Timer -> PublishSubject:A (Source1)" in lines


def test_example_rig_diff_names_the_fixes():
    d = baghban.diff(baghban.load(V1), baghban.load(V2))
    text = d.summary()
    assert "~ Timer  Period: PT10S -> PT12S" in text
    assert "CsvWriter#1 ('licks.csv')  enabled" in text
    assert "- SubscribeSubject:TrialEnds" in text and "+ SubscribeSubject:TrialEnd" in text


# ------------------------------------------------------------------ fingerprint

def test_fingerprint_ignores_format_and_version_but_not_content():
    xml = workflow(expr(timer()), expr(csv_writer()), edges=[(0, 1)])
    base = document(xml)
    same = base.replace("><", ">\n <").replace('Version="2.9.0"', 'Version="2.9.1"')
    other = document(workflow(expr(timer("PT9S")), expr(csv_writer()), edges=[(0, 1)]))
    fp = baghban.fingerprint
    assert fp(baghban.loads(base)) == fp(baghban.loads(same))
    assert fp(baghban.loads(base)) != fp(baghban.loads(other))


def test_fingerprint_sees_included_content():
    assert baghban.fingerprint(baghban.load(V1)) != baghban.fingerprint(baghban.load(V2))


def test_manifest_fields():
    fields = baghban.manifest_fields(baghban.load(V2))
    assert fields["bonsai.param.TrialInterval"] == "PT12S"
    assert fields["bonsai.include.modules/CameraRecorder.bonsai"] == "ok"
    assert len(fields["bonsai.fingerprint"]) == 64


def test_parameters_and_dependencies():
    doc = baghban.load(V1)
    params = baghban.parameters(doc)
    assert params == [{"name": "TrialInterval", "property": "Period", "value": "PT10S",
                       "targets": ["Timer #5"]}]
    deps = baghban.dependencies(doc)
    assert set(deps["assemblies"]) == {"Bonsai.Core", "Bonsai.System", "Bonsai.Vision"}


# ------------------------------------------------------------------ render

def test_mermaid_has_subgraphs_and_highlights():
    doc = baghban.load(V1)
    text = baghban.mermaid(doc, baghban.check(doc).findings)
    assert text.startswith("flowchart LR")
    assert "subgraph n_6" in text  # SelectMany 'Trial'
    assert "stroke:#d62728" in text  # error highlighted
    ids = [line.split("[")[0].strip() for line in text.splitlines() if '["' in line
           and not line.strip().startswith("subgraph")]
    assert len(ids) == len(set(ids))


def test_dot_and_html():
    doc = baghban.load(V1)
    assert "subgraph cluster_n_6" in baghban.dot(doc)
    page = baghban.html(doc, baghban.check(doc))
    assert "<pre class=\"mermaid\">" in page and "DANGLING_SUBJECT" in page


def test_outline():
    text = baghban.outline(baghban.load(V1))
    assert "SelectMany 'Trial'" in text and "[disabled]" in text
    assert "exposes Period as TrialInterval" in text


# ------------------------------------------------------------------ cli

def test_cli_check_exit_codes(capsys):
    assert main(["check", str(V1)]) == 1
    assert main(["check", str(V2)]) == 0
    capsys.readouterr()


def test_cli_check_json(capsys):
    main(["check", str(V1), "--json"])
    data = json.loads(capsys.readouterr().out)
    codes = {f["code"] for f in data["reports"][0]["findings"]}
    assert {"DUPLICATE_OUTPUT", "SILENT_OVERWRITE", "DANGLING_SUBJECT", "DISABLED_WRITER"} <= codes


def test_cli_directory_checks_modules_through_includer(capsys):
    assert main(["check", str(EXAMPLES / "rig_v2")]) == 0
    out = capsys.readouterr().out
    assert "1 file(s) checked through the workflows that include them" in out


def test_cli_strict_fails_on_warnings(capsys, tmp_path):
    from xmlkit import externalized
    path = tmp_path / "w.bonsai"
    path.write_text(document(workflow(expr(timer()), expr(externalized("FileName")),
                                      expr(csv_writer(overwrite=True)),
                                      edges=[(0, 2), (1, 2, "Source2")])))
    assert main(["check", str(path)]) == 0            # info only
    assert main(["check", str(path), "--strict"]) == 0  # info never fails
    capsys.readouterr()
    warn = tmp_path / "warn.bonsai"
    warn.write_text(document(workflow(expr(("SubscribeSubject", "")))))
    assert main(["check", str(warn)]) == 0
    assert main(["check", str(warn), "--strict"]) == 1
    capsys.readouterr()


def test_cli_diff_and_render(capsys, tmp_path):
    assert main(["diff", str(V1), str(V1)]) == 0
    assert main(["diff", str(V1), str(V2)]) == 1
    out = tmp_path / "rig.html"
    assert main(["render", str(V1), "-o", str(out)]) == 0
    assert out.read_text().startswith("<!doctype html>")
    for cmd in (["show", str(V1)], ["deps", str(V1)], ["params", str(V1)],
                ["fingerprint", str(V1)], ["fingerprint", str(V1), "--fields"],
                ["render", str(V1), "-f", "mermaid"], ["render", str(V1), "-f", "dot"]):
        assert main(cmd) == 0
    capsys.readouterr()


def test_cli_exclude(capsys, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "snippet.bonsai").write_text(document(workflow(expr(subscribe("X")))))
    (tmp_path / "rig.bonsai").write_text(document(workflow(expr(timer()))))
    assert main(["check", str(tmp_path)]) == 1
    assert main(["check", str(tmp_path), "--exclude", "docs/*"]) == 0
    capsys.readouterr()
