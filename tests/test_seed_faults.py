"""The recall kit (survey/seed_faults.py): every kind of planted fault, on a
small workflow, produces exactly the finding it is meant to, at the planted
node. So a miss on real rigs is baghban's, not the kit's."""

import importlib.util
from pathlib import Path

import pytest

import baghban
from xmlkit import (csv_writer, document, expr, externalized, include_expr, publish, subscribe,
                    timer, workflow)

etree = pytest.importorskip("lxml.etree")
spec = importlib.util.spec_from_file_location(
    "seed_faults", Path(__file__).parents[1] / "survey" / "seed_faults.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


@pytest.fixture
def rig(tmp_path):
    (tmp_path / "Mod.bonsai").write_text(document(workflow(expr(timer()))))
    path = tmp_path / "rig.bonsai"
    path.write_text(document(workflow(
        expr(timer()), expr(publish("Ticks")), expr(subscribe("Ticks")),
        expr(csv_writer("a.csv")), expr(externalized(("Period", "Interval"))), expr(timer()),
        expr(csv_writer("b.csv")), include_expr("Mod.bonsai"),
        edges=[(0, 1), (2, 3), (4, 5), (5, 6)])))
    return path


def test_the_rig_is_clean_and_round_trips(rig):
    assert baghban.check(baghban.load(rig)).findings == []
    assert seed.round_trips(rig, {})


@pytest.mark.parametrize("kind", list(seed.EXPECTED))
def test_each_planted_fault_is_found_where_it_was_planted(rig, kind):
    doc = baghban.load(rig)
    site = next((s for s in seed.sites(doc) if s[0] == kind), None)
    assert site is not None, f"no site for {kind}"
    _, node, extra = site
    tree = etree.parse(str(rig), seed.PARSER)
    targets = seed.plant(tree.getroot(), kind, node, extra)
    planted = rig.with_name("planted.bonsai")
    tree.write(str(planted), xml_declaration=True, encoding="utf-8")
    report = baghban.check(baghban.load(planted))
    codes = {f.code for f in report.findings}
    assert seed.EXPECTED[kind] in codes
    assert any(f.code == seed.EXPECTED[kind] and f.node in targets for f in report.findings)


def test_externalized_subject_names_are_not_planted(tmp_path):
    path = tmp_path / "m.bonsai"
    path.write_text(document(workflow(expr(externalized("Name")), expr(subscribe("S")),
                                      expr(csv_writer("a.csv")), edges=[(0, 1), (1, 2)])))
    kinds = {k for k, _, _ in seed.sites(baghban.load(path))}
    assert "dangling_subject" not in kinds and "unnamed_subject" not in kinds
