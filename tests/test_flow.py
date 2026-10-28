"""Loops that run once (baghban.flow): roadmap item 5.

Each rule is the behaviour of a Bonsai operator as its source implements it
(see the module docstring). Every rule is tested in both directions. A loop
baghban cannot show runs once stays a loop, so these tests also pin what
stays an error.
"""

import pytest

import baghban
from baghban.flow import FlowAnalysis
from xmlkit import (combinator, csv_writer, defer, disable, document, expr, externalized, group,
                    include_expr, select_many, subscribe, timer, workflow, workflow_input,
                    workflow_output)


def once_timer():
    return combinator("rx:Timer", "<rx:DueTime>PT1S</rx:DueTime>")


def op(name, body=""):
    return combinator(f"rx:{name}", body)


def take(n):
    return op("Take", f"<rx:Count>{n}</rx:Count>")


def flow_of(*nodes, edges, index=-1):
    xml = [n if isinstance(n, str) else expr(n) for n in nodes]  # disable() gives markup
    doc = baghban.loads(document(workflow(*xml, edges=edges)))
    return FlowAnalysis().flow(doc.workflow.nodes[index])


def chain(*nodes):
    """nodes in a line; the flow of the last one."""
    return flow_of(*nodes, edges=[(i, i + 1) for i in range(len(nodes) - 1)])


# ------------------------------------------------------------------ the rules

@pytest.mark.parametrize("nodes,one", [
    ((once_timer(),), True),
    ((timer("PT1S"),), False),  # periodic
    ((combinator("rx:Timer", "<rx:DueTime>PT1S</rx:DueTime><rx:Period>PT0S</rx:Period>"),), True),
    ((timer(), op("LastOrDefault")), True),
    ((timer(), op("First")), True),
    ((timer(), op("Count")), True),
    ((timer(), take(1)), True),
    ((timer(), take(2)), False),
    ((timer(), op("TakeLast", "<rx:Count>1</rx:Count>")), True),
    ((("Unit", ""),), True),  # Observable.Return
    ((("IntProperty", "<Value>3</Value>"),), False),  # re-emits when the property changes
    ((once_timer(), ("IntProperty", "<Value>3</Value>")), True),  # Select(x => value)
    ((once_timer(), op("Timestamp")), True),
    ((once_timer(), op("Skip", "<rx:Count>0</rx:Count>")), True),
    ((once_timer(), ("MulticastSubject", "<Name>S</Name>")), True),
    ((once_timer(), csv_writer("a.csv")), True),  # writers pass elements on
    ((once_timer(), op("Scan")), False),  # not in the list: not known
    ((subscribe("S"),), False),  # subjects are not followed
])
def test_rules(nodes, one):
    assert chain(*nodes).one is one


def test_disabled_and_many_inputs_are_not_known():
    assert not flow_of(once_timer(), disable(op("LastOrDefault")), edges=[(0, 1)]).one
    merge = flow_of(once_timer(), once_timer(), op("Merge"), edges=[(0, 2), (1, 2, "Source2")])
    assert not merge.one  # two singles merge into two


def test_by_first_input_and_zip():
    # TakeUntil(source, trigger): no more than the source
    assert flow_of(once_timer(), timer(), op("TakeUntil"), edges=[(0, 2), (1, 2, "Source2")]).one
    assert not flow_of(timer(), once_timer(), op("TakeUntil"),
                       edges=[(0, 2), (1, 2, "Source2")]).one
    assert flow_of(timer(), once_timer(), op("Zip"), edges=[(0, 2), (1, 2, "Source2")]).one


def test_nested_workflows():
    inner_once = workflow(expr(workflow_input()), expr(op("LastOrDefault")), expr(workflow_output()),
                          edges=[(0, 1), (1, 2)])
    inner_pass = workflow(expr(workflow_input()), expr(workflow_output()), edges=[(0, 1)])
    # SelectMany: per element; one element in, at most one out each time
    assert flow_of(once_timer(), select_many(inner_pass), edges=[(0, 1)]).one
    assert not flow_of(timer(), select_many(inner_once), edges=[(0, 1)]).one  # many elements
    # a group passes its input in and its output on
    assert flow_of(once_timer(), group("G", inner_pass), edges=[(0, 1)]).one
    assert not flow_of(timer(), group("G", inner_pass), edges=[(0, 1)]).one
    # Defer with no input: what its workflow outputs
    src = workflow(expr(timer()), expr(op("LastOrDefault")), expr(workflow_output()),
                   edges=[(0, 1), (1, 2)])
    assert chain(defer(src)).one


def test_selectmany_input_is_one_element_unless_elements_are_observables():
    inner = workflow(expr(workflow_input()), expr(workflow_output()), edges=[(0, 1)])
    ok = flow_of(timer(), select_many(inner), edges=[(0, 1)])  # each element: Return(x)
    windows = flow_of(timer(), op("WindowCount", "<rx:Count>5</rx:Count>"), op("LastOrDefault"),
                      select_many(inner), edges=[(0, 1), (1, 2), (2, 3)])
    doc = baghban.loads(document(workflow(expr(timer()), expr(select_many(inner)),
                                          edges=[(0, 1)])))
    a = FlowAnalysis()
    assert a.workflow_input(doc.workflow.nodes[1].workflow).one
    # one window, passed in whole: its elements are many
    assert not windows.one
    assert not ok.one  # many elements in, so many out


# ------------------------------------------------------------------ writers

def loop_with_writer(source_nodes, writer, *, name="Trial", after=()):
    inner = workflow(expr(workflow_input()), expr(writer), expr(workflow_output()),
                     edges=[(0, 1), (1, 2)])
    loop = ("rx:SelectMany", f"<Name>{name}</Name><Workflow>{inner}</Workflow>")
    nodes = list(source_nodes) + [loop] + list(after)
    return document(workflow(*map(expr, nodes), edges=[(i, i + 1) for i in range(len(nodes) - 1)]))


def report(xml):
    return baghban.check(baghban.loads(xml))


def test_overwrite_in_a_loop_that_runs_once_is_the_across_run_warning():
    r = report(loop_with_writer([timer(), op("LastOrDefault")], csv_writer("t.csv", overwrite=True)))
    [f] = r.findings
    assert (f.code, f.severity) == ("SILENT_OVERWRITE", "warning")
    assert "receives at most one element per run (bounded by LastOrDefault" in f.message
    assert "opened once per run" in f.message


def test_overwrite_in_a_loop_that_may_repeat_stays_an_error():
    r = report(loop_with_writer([timer()], csv_writer("t.csv", overwrite=True)))
    assert [(f.code, f.severity) for f in r.findings] == [("SILENT_OVERWRITE", "error")]


def test_fails_on_repeat_is_quiet_when_the_loop_runs_once():
    assert report(loop_with_writer([once_timer()], csv_writer("t.csv"))).codes() == []
    assert report(loop_with_writer([timer()], csv_writer("t.csv"))).codes() == ["FAILS_ON_REPEAT"]


def test_repeat_downstream_runs_the_loop_again():
    xml = loop_with_writer([once_timer()], csv_writer("t.csv", overwrite=True),
                           after=[op("Repeat")])
    assert [(f.code, f.severity) for f in report(xml).findings] == [("SILENT_OVERWRITE", "error")]


def test_every_enclosing_loop_must_run_once():
    writer_loop = workflow(expr(workflow_input()), expr(csv_writer("t.csv", overwrite=True)),
                           expr(workflow_output()), edges=[(0, 1), (1, 2)])
    inner = workflow(expr(workflow_input()), expr(select_many(writer_loop)), expr(workflow_output()),
                     edges=[(0, 1), (1, 2)])
    # the outer loop repeats; the inner one gets one element each time: still per trial
    xml = document(workflow(expr(timer()), expr(select_many(inner)), edges=[(0, 1)]))
    assert [(f.code, f.severity) for f in report(xml).findings] == [("SILENT_OVERWRITE", "error")]
    # both run once
    xml = document(workflow(expr(once_timer()), expr(select_many(inner)), edges=[(0, 1)]))
    [f] = report(xml).findings
    assert f.severity == "warning" and "Every loop around it" in f.message


def test_createobservable_is_never_once():
    inner = workflow(expr(workflow_input()), expr(csv_writer("t.csv", overwrite=True)),
                     expr(workflow_output()), edges=[(0, 1), (1, 2)])
    xml = document(workflow(expr(once_timer()),
                            expr(("rx:CreateObservable", f"<Workflow>{inner}</Workflow>")),
                            edges=[(0, 1)]))
    assert [(f.code, f.severity) for f in report(xml).findings] == [("SILENT_OVERWRITE", "error")]


def test_window_workflow_is_a_loop():
    # Bonsai.Reactive.Window subscribes its nested workflow once per window
    inner = workflow(expr(workflow_input()), expr(csv_writer("t.csv", overwrite=True)),
                     expr(workflow_output()), edges=[(0, 1), (1, 2)])
    xml = document(workflow(expr(timer()), expr(("rx:Window", f"<Workflow>{inner}</Workflow>")),
                            edges=[(0, 1)]))
    assert [(f.code, f.severity) for f in report(xml).findings] == [("SILENT_OVERWRITE", "error")]


def test_iblrig_shape(tmp_path):
    # iblrig's sequential stages: a Defer'd include ending in LastOrDefault, then
    # SelectMany stages each ending in LastOrDefault; the stimulus loop holds an
    # include whose group writes NoiseLocations.bin (Overwrite=True, Suffix=None).
    (tmp_path / "Spacer.bonsai").write_text(document(workflow(
        expr(timer()), expr(op("LastOrDefault")), expr(workflow_output()), edges=[(0, 1), (1, 2)])))
    (tmp_path / "RF.bonsai").write_text(document(workflow(
        expr(workflow_input()),
        expr(("Combinator", '<Combinator xsi:type="io:CsvWriter"><io:FileName>NoiseLocations.bin'
              '</io:FileName><io:Overwrite>true</io:Overwrite><io:Suffix>None</io:Suffix>'
              '</Combinator>')),
        expr(workflow_output()), edges=[(0, 1), (1, 2)])))
    stage = workflow(expr(workflow_input()), include_expr("Spacer.bonsai"),
                     expr(op("LastOrDefault")), expr(("IntProperty", "<Value>1</Value>")),
                     expr(("MulticastSubject", "<Name>SyncState</Name>")), expr(workflow_output()),
                     edges=[(1, 2), (2, 3), (3, 4), (4, 5)])
    rf = workflow(expr(workflow_input()), include_expr("RF.bonsai"), expr(workflow_output()),
                  edges=[(0, 1), (1, 2)])
    xml = document(workflow(
        expr(("rx:Defer", f"<Name>Spacer</Name><Workflow>{workflow(include_expr('Spacer.bonsai'), expr(workflow_output()), edges=[(0, 1)])}</Workflow>")),
        expr(("rx:SelectMany", f"<Name>Spontaneous</Name><Workflow>{stage}</Workflow>")),
        expr(("rx:SelectMany", f"<Name>ReceptiveFieldMappingStim</Name><Workflow>{rf}</Workflow>")),
        expr(("PublishSubject", "<Name>SyncState</Name>")),
        edges=[(0, 1), (1, 2)]))
    r = baghban.check(baghban.loads(xml, base_dir=tmp_path))
    [f] = [f for f in r.findings if f.code == "SILENT_OVERWRITE"]
    assert f.severity == "warning"
    assert "ReceptiveFieldMappingStim" in f.message and "LastOrDefault" in f.message
