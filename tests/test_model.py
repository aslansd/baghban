from pathlib import Path

import pytest

import baghban
from baghban.model import TypeRef, parse_namespace_uri
from xmlkit import (camera, csv_writer, disable, document, expr, externalized, group,
                    include_expr, publish, select_many, timer, video_writer, workflow,
                    workflow_input)


def test_namespace_uri():
    assert parse_namespace_uri("clr-namespace:Bonsai.Vision;assembly=Bonsai.Vision") == \
        ("Bonsai.Vision", "Bonsai.Vision")
    assert parse_namespace_uri("https://bonsai-rx.org/2018/workflow") == \
        ("Bonsai.Expressions", "Bonsai.Core")


def test_types_resolve_through_xmlns():
    doc = baghban.loads(document(workflow(expr(timer()), expr(camera()), expr(csv_writer()))))
    t, c, w = doc.workflow.nodes
    assert t.type == TypeRef("Timer", "Bonsai.Reactive", "Bonsai.Core") and t.wrapper == "Combinator"
    assert c.type.qualified == "Bonsai.Vision.CameraCapture"
    assert w.type.assembly == "Bonsai.System" and w.wrapper is None


def test_properties_are_flat_dotted_keys():
    doc = baghban.loads(document(workflow(expr(timer("PT2S")))))
    assert doc.workflow.nodes[0].properties == {"DueTime": "PT0S", "Period": "PT2S"}


def test_nested_typed_properties():
    xml = workflow('<Expression xsi:type="Multiply"><Operand xsi:type="IntProperty">'
                   '<Value>2</Value></Operand></Expression>')
    node = baghban.loads(document(xml)).workflow.nodes[0]
    assert node.properties == {"Operand@type": "IntProperty", "Operand.Value": "2"}


def test_disable_is_unwrapped():
    node = baghban.loads(document(workflow(disable(video_writer())))).workflow.nodes[0]
    assert node.disabled and node.type.name == "VideoWriter" and node.is_writer


def test_writer_detection():
    doc = baghban.loads(document(workflow(expr(csv_writer()), expr(video_writer()), expr(timer()))))
    assert [n.is_writer for n in doc.workflow.nodes] == [True, True, False]


def test_scopes():
    inner_g = workflow(expr(workflow_input()), expr(publish("A")))
    inner_s = workflow(expr(workflow_input()), expr(publish("B")))
    doc = baghban.loads(document(workflow(expr(group("G", inner_g)), expr(select_many(inner_s)))))
    g, s = doc.workflow.nodes
    assert g.workflow.transparent and g.workflow.scope() is doc.workflow
    assert not s.workflow.transparent and s.workflow.scope() is s.workflow
    assert s.workflow.parent_scope() is doc.workflow
    assert s.workflow.nodes[1].repeating_container() is s


def test_ids_and_locations():
    inner = workflow(expr(workflow_input()), expr(publish("B")))
    doc = baghban.loads(document(workflow(expr(timer()), expr(group("G", inner)))))
    node = doc.workflow.nodes[1].workflow.nodes[1]
    assert node.id == (1, 1)
    assert node.location() == "Group 'G' #1 > PublishSubject 'B' #1"


def test_bom_and_real_file(tmp_path):
    path = tmp_path / "bom.bonsai"
    path.write_bytes("\ufeff".encode("utf-8") + document(workflow(expr(timer()))).encode("utf-8"))
    assert baghban.load(path).version == "2.9.0"


def test_not_a_workflow(tmp_path):
    bad = tmp_path / "x.bonsai"
    bad.write_text("<Other/>")
    with pytest.raises(baghban.WorkflowLoadError):
        baghban.load(bad)
    bad.write_text("<WorkflowBuilder")
    with pytest.raises(baghban.WorkflowLoadError):
        baghban.load(bad)


def test_include_is_expanded_and_overridden(tmp_path):
    module = workflow(expr(workflow_input()), expr(video_writer("x.avi")),
                      expr(externalized(("FileName", "Video"))), edges=[(0, 1), (2, 1, "Source2")])
    (tmp_path / "M.bonsai").write_text(document(module))
    doc = baghban.loads(document(workflow(expr(camera()), include_expr("M.bonsai", Video="left.avi"),
                                          edges=[(0, 1)])), base_dir=tmp_path)
    inc = doc.workflow.nodes[1]
    assert inc.include.status == "ok" and inc.workflow.from_include
    writer = inc.workflow.nodes[1]
    assert writer.properties["FileName"] == "left.avi" and "FileName" in writer.overridden
    assert writer.file == (tmp_path / "M.bonsai").resolve()
    assert doc.included_files == [(tmp_path / "M.bonsai").resolve()]


def test_edges_and_neighbours():
    doc = baghban.loads(document(workflow(expr(timer()), expr(externalized("FileName")),
                                          expr(csv_writer()), edges=[(0, 2), (1, 2, "Source2")])))
    w = doc.workflow.nodes[2]
    assert [n.index for n in w.predecessors()] == [0, 1]
    assert w.externalized() == {"FileName"}


def test_examples_load():
    root = Path(__file__).parents[1] / "examples"
    for path in root.rglob("foraging.bonsai"):
        assert sum(1 for _ in baghban.load(path).walk()) > 10
