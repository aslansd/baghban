"""Launcher values (baghban.launch) and provenance (baghban.provenance).

The rules are Bonsai's, read from its source: CommandLineParser and
PropertyAssignment (Bonsai.Configuration) for the command line,
ExpressionBuilderGraphExtensions.SetWorkflowProperty and
WorkflowTypeDescriptor (Bonsai.Core) for where a value goes.
"""

import json
from pathlib import Path

import pytest

import baghban
from baghban.cli import main
from xmlkit import (csv_writer, disable, document, expr, externalized, group, include_expr,
                    property_mapping, select_many, timer, workflow, workflow_input)


# ------------------------------------------------------------------ command line

def test_every_spelling_of_property():
    launch = baghban.parse_command_line(
        ["rig.bonsai", "--property:A=1", "--property", "B=2", "-p:C=3", "-p", "D=4"])
    assert launch.workflow == "rig.bonsai"
    assert launch.properties == {"A": "1", "B": "2", "C": "3", "D": "4"}


def test_leading_executable_and_other_commands():
    launch = baghban.parse_command_line(
        [r"C:\Bonsai\Bonsai.exe", "rig.bonsai", "--no-editor", "--start", "--lib", "a",
         "--lib:b", "-vl", "layout.xml", "--startnodebug", "-p:Animal=M12"])
    assert launch.workflow == "rig.bonsai"
    assert launch.options == {"--no-editor": True, "--start": True, "--lib": ["a", "b"],
                              "--visualizer-layout": "layout.xml", "--start-no-debug": True}
    assert launch.properties == {"Animal": "M12"}


def test_value_is_split_at_the_first_colon_and_first_equals():
    launch = baghban.parse_command_line([r"-p:Path=C:\data\a=b.csv"])
    assert launch.properties == {"Path": r"C:\data\a=b.csv"}


def test_value_starting_with_a_long_command_is_not_taken():
    # Bonsai passes "" to PropertyAssignment.Parse, which throws
    with pytest.raises(ValueError, match="NAME=VALUE"):
        baghban.parse_command_line(["--property", "--start"])
    # a single dash is taken as the value, as Bonsai does
    assert baghban.parse_command_line(["-p", "-x=1"]).properties == {"-x": "1"}


@pytest.mark.parametrize("args,why", [
    (["a.bonsai", "b.bonsai"], "unrecognized"),
    (["-p:A=1", "-p:A=2"], "twice"),
    (["-p:A"], "invalid property assignment"),
])
def test_command_lines_bonsai_refuses(args, why):
    with pytest.raises(ValueError, match=why):
        baghban.parse_command_line(args)


# ------------------------------------------------------------------ fixtures

def rig(*nodes, edges=()):
    return baghban.loads(document(workflow(*nodes, edges=edges)))


def interval():
    """Top level: TrialInterval -> Timer.Period."""
    return rig(expr(externalized(("Period", "TrialInterval"))), expr(timer("PT10S")),
               edges=[(0, 1)])


def stim_group(name="Stim", period="PT1S"):
    """A group exposing the Period of a Timer inside it as 'Interval'."""
    inner = workflow(expr(externalized(("Period", "Interval"))), expr(timer(period)),
                     edges=[(0, 1)])
    return group(name, inner)


# ------------------------------------------------------------------ set_properties

def test_top_level_property():
    doc = interval()
    [a] = baghban.set_properties(doc, {"TrialInterval": "PT3S"})
    assert (a.status, a.value, a.previous) == ("ok", "PT3S", "PT10S")
    assert a.targets == ["Timer #1.Period"]
    t = doc.workflow.nodes[1]
    assert t.properties["Period"] == "PT3S" and "Period" in t.overridden
    assert baghban.parameters(doc)[0]["value"] == "PT3S"


def test_dotted_name_walks_into_named_groups_and_nested_workflows():
    sm = ("rx:SelectMany", f"<Name>Trial</Name><Workflow>{workflow(expr(stim_group()))}</Workflow>")
    doc = rig(expr(sm))
    [a] = baghban.set_properties(doc, {"Trial.Stim.Interval": "PT2S"})
    assert a.status == "ok"
    timer_node = doc.workflow.nodes[0].workflow.nodes[0].workflow.nodes[1]
    assert timer_node.properties["Period"] == "PT2S"
    # empty parts are dropped, as Split(..., RemoveEmptyEntries) does
    assert baghban.set_properties(doc, {"Trial..Stim.Interval.": "PT4S"})[0].status == "ok"
    assert timer_node.properties["Period"] == "PT4S"


def test_value_reaches_through_an_include_and_a_group_inside_it(tmp_path):
    # iblrig's shape: Stim.ReceptiveFieldMappingStim.FileNameRFMapStim, where the
    # last group maps the name onto an include, whose own mapping feeds a group
    # holding the writer.
    inner_group = group("Noise", workflow(expr(externalized(("FileName", "FileNameRF"))),
                                          expr(csv_writer("NoiseLocations.bin")), edges=[(0, 1)]))
    module = workflow(expr(externalized("FileNameRF")), expr(inner_group), edges=[(0, 1)])
    (tmp_path / "RF.bonsai").write_text(document(module))
    rf = group("RF", workflow(expr(externalized("FileNameRF")),
                              include_expr("RF.bonsai", FileNameRF="NoiseLocations.bin"),
                              edges=[(0, 1)]))
    doc = baghban.loads(document(workflow(expr(group("Stim", workflow(expr(rf)))))),
                        base_dir=tmp_path)
    [a] = baghban.set_properties(doc, {"Stim.RF.FileNameRF": "session42.bin"})
    assert (a.status, a.previous) == ("ok", "NoiseLocations.bin")
    [out] = baghban.outputs(doc)
    assert out["path"] == "session42.bin" and out["overridden"]
    include = doc.workflow.nodes[0].workflow.nodes[0].workflow.nodes[1]
    assert include.properties["FileNameRF"] == "session42.bin"


def test_include_override_reaches_a_group_inside_the_include(tmp_path):
    # fixed in 0.4.0: values on an IncludeWorkflow element did not go on into groups
    module = workflow(expr(externalized(("FileName", "Log"))),
                      expr(group("G", workflow(expr(externalized("FileName")),
                                               expr(csv_writer("x.csv")), edges=[(0, 1)]))),
                      edges=[(0, 1)])
    (tmp_path / "M.bonsai").write_text(document(module))
    doc = baghban.loads(document(workflow(include_expr("M.bonsai", Log="left.csv"))),
                        base_dir=tmp_path)
    assert [o["path"] for o in baghban.outputs(doc)] == ["left.csv"]


def test_parameters_reports_the_value_inside_a_group():
    doc = rig(expr(externalized("Interval")), expr(stim_group(period="PT7S")), edges=[(0, 1)])
    assert baghban.parameters(doc)[0]["value"] == "PT7S"


@pytest.mark.parametrize("name,status,note", [
    ("Nope", "unknown", "exposes TrialInterval"),
    ("Stim.Nope", "unknown", "no nested workflow named 'Stim'"),
    ("  ", "invalid", "empty"),
])
def test_names_bonsai_would_refuse(name, status, note):
    doc = interval()
    [a] = baghban.set_properties(doc, {name: "1"})
    assert a.status == status and note in a.note
    assert doc.workflow.nodes[1].properties["Period"] == "PT10S"


def test_ambiguous_and_disabled_groups():
    doc = rig(expr(stim_group()), expr(stim_group()), disable(stim_group("Off")))
    [amb, off] = baghban.set_properties(doc, {"Stim.Interval": "PT2S", "Off.Interval": "PT2S"})
    assert amb.status == "ambiguous" and "2 nested workflows" in amb.note
    assert off.status == "unknown" and "disabled" in off.note


def test_include_is_not_walked_into_by_name(tmp_path):
    (tmp_path / "Mod.bonsai").write_text(document(workflow(expr(timer()))))
    doc = baghban.loads(document(workflow(include_expr("Mod.bonsai"))), base_dir=tmp_path)
    [a] = baghban.set_properties(doc, {"Mod.Period": "PT1S"})
    assert a.status == "unknown" and "is an include" in a.note


def test_first_property_of_a_name_wins():
    doc = rig(expr(externalized(("Period", "T"))), expr(timer("PT1S")),
              expr(externalized(("Period", "T"))), expr(timer("PT2S")), edges=[(0, 1), (2, 3)])
    baghban.set_properties(doc, {"T": "PT9S"})
    assert [n.properties["Period"] for n in doc.workflow.nodes[1::2]] == ["PT9S", "PT2S"]


def test_unconnected_property_is_set_but_goes_nowhere():
    [a] = baghban.set_properties(rig(expr(externalized("Period"))), {"Period": "PT1S"})
    assert a.status == "ok" and a.targets == [] and "not connected" in a.note


def test_strict_raises_before_changing_anything():
    doc = interval()
    with pytest.raises(baghban.PropertyAssignmentError, match="Nope"):
        baghban.set_properties(doc, {"TrialInterval": "PT3S", "Nope": "1"}, strict=True)
    assert doc.workflow.nodes[1].properties["Period"] == "PT10S"


# ------------------------------------------------------------------ outputs

def test_outputs_skip_disabled_writers_and_flag_run_time_paths():
    doc = rig(expr(csv_writer("a.csv", suffix="Timestamp")), disable(csv_writer("b.csv")),
              expr(property_mapping("FileName")), expr(csv_writer("c.csv")), edges=[(2, 3)])
    outs = baghban.outputs(doc)
    assert [(o["path"], o["suffix"], o["set_at_run_time"]) for o in outs] == \
        [("a.csv", "Timestamp", False), ("c.csv", "None", True)]
    assert outs[0]["writer"] == "CsvWriter" and outs[0]["property"] == "FileName"


# ------------------------------------------------------------------ provenance

def write_rig(tmp_path):
    path = tmp_path / "rig.bonsai"
    path.write_text(document(workflow(expr(externalized(("Period", "TrialInterval"))),
                                      expr(timer("PT10S")), expr(csv_writer("events.csv")),
                                      edges=[(0, 1), (1, 2)])))
    return path


def test_provenance_fields(tmp_path):
    path = write_rig(tmp_path)
    doc = baghban.load(path)
    fields = baghban.provenance(doc, {"TrialInterval": "PT3S"})
    assert fields["bonsai.provenance"] == "1"
    assert fields["bonsai.baghban"] == baghban.__version__
    assert fields["bonsai.workflow"] == str(path.resolve())
    assert fields["bonsai.version"] == "2.9.0"
    assert fields["bonsai.property.TrialInterval"] == "PT3S"
    assert fields["bonsai.param.TrialInterval"] == "PT3S"
    assert fields["bonsai.output.0"] == "events.csv"
    assert "bonsai.problems" not in fields
    assert all(isinstance(v, str) for v in fields.values())
    # the fingerprint is of the file as saved, and the document is not changed
    assert fields["bonsai.fingerprint"] == baghban.fingerprint(doc)
    assert baghban.parameters(doc)[0]["value"] == "PT10S"


def test_provenance_from_a_command_line(tmp_path):
    write_rig(tmp_path)
    fields = baghban.provenance(command_line=["Bonsai.exe", "rig.bonsai", "--no-editor",
                                              "-p:TrialInterval=PT5S", "-p:Nope=1"],
                                cwd=tmp_path)
    assert fields["bonsai.param.TrialInterval"] == "PT5S"
    assert fields["bonsai.problems"].startswith("--property Nope:")
    with pytest.raises(ValueError, match="no workflow"):
        baghban.provenance(command_line=["--no-editor"])


def test_manifest_fields_is_provenance_without_launcher_values(tmp_path):
    doc = baghban.load(write_rig(tmp_path))
    assert baghban.manifest_fields(doc) == baghban.provenance(doc)


def test_no_dependency_on_daftar():
    # daftar depends on baghban (its Bonsai adapter), never the other way round
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert "daftar" not in pyproject.split("[project.urls]")[0].split("description")[1]


# ------------------------------------------------------------------ command line tool

def test_cli_params_and_provenance_take_properties(tmp_path, capsys):
    path = str(write_rig(tmp_path))
    assert main(["params", path, "-p", "TrialInterval=PT3S"]) == 0
    assert "= PT3S" in capsys.readouterr().out
    assert main(["provenance", path, "--property", "TrialInterval=PT4S"]) == 0
    assert json.loads(capsys.readouterr().out)["bonsai.param.TrialInterval"] == "PT4S"
    assert main(["fingerprint", path, "--fields", "-p", "TrialInterval=PT4S"]) == 0
    assert json.loads(capsys.readouterr().out)["bonsai.property.TrialInterval"] == "PT4S"


def test_cli_unknown_property_exits_1(tmp_path, capsys):
    path = str(write_rig(tmp_path))
    assert main(["params", path, "-p", "Nope=1"]) == 1
    assert main(["check", path, "-p", "Nope=1"]) == 1
    assert main(["provenance", path, "-p", "Nope=1"]) == 1
    assert "Bonsai would refuse it" in capsys.readouterr().err


def test_cli_property_misuse(tmp_path):
    path = str(write_rig(tmp_path))
    with pytest.raises(SystemExit, match="as saved"):
        main(["fingerprint", path, "-p", "TrialInterval=PT1S"])
    with pytest.raises(SystemExit, match="one workflow"):
        main(["check", path, path, "-p", "TrialInterval=PT1S"])
    with pytest.raises(SystemExit, match="twice"):
        main(["params", path, "-p", "A=1", "-p", "A=2"])
