"""Every finding is tested in both directions: it must fire where the problem
exists and stay quiet on the nearest workflow that does not have it. A
checker that cries wolf on good rigs gets switched off."""

import pytest

import baghban
from xmlkit import (behavior, camera, csv_writer, defer, disable, document, expr, externalized,
                    group, include_expr, multicast, property_mapping, publish, select_many,
                    subscribe, timer, video_writer, workflow, workflow_input, workflow_output)


def codes(xml, tmp_path=None, **kw):
    base = tmp_path if tmp_path is not None else "."
    return baghban.check(baghban.loads(document(xml), base_dir=base, **kw)).codes()


def single(writer, *, in_loop=False, source=None):
    """source -> writer, optionally inside a SelectMany."""
    source = source or timer()
    if in_loop:
        inner = workflow(expr(workflow_input()), expr(writer), expr(workflow_output()),
                         edges=[(0, 1), (1, 2)])
        return workflow(expr(source), expr(select_many(inner)), edges=[(0, 1)])
    return workflow(expr(source), expr(writer), edges=[(0, 1)])


# ------------------------------------------------------------ SILENT_OVERWRITE

def test_overwrite_without_suffix_fires():
    assert codes(single(csv_writer(overwrite=True))) == ["SILENT_OVERWRITE"]


@pytest.mark.parametrize("suffix", ["Timestamp", "FileCount"])
def test_overwrite_with_suffix_is_quiet(suffix):
    assert codes(single(csv_writer(overwrite=True, suffix=suffix))) == []


def test_no_overwrite_outside_loop_is_quiet():
    # a second run stops loudly at start; nothing is lost
    assert codes(single(csv_writer(overwrite=False))) == []


def test_overwrite_applies_to_filesink_writers_too():
    assert codes(single(video_writer(overwrite=True), source=camera())) == ["SILENT_OVERWRITE"]


def test_overwrite_inside_selectmany_is_per_trial():
    report = baghban.check(baghban.loads(document(single(csv_writer(overwrite=True), in_loop=True))))
    assert report.codes() == ["SILENT_OVERWRITE"]
    assert "every element" in report.findings[0].message


def test_overwrite_inside_group_is_not_a_loop():
    inner = workflow(expr(workflow_input()), expr(csv_writer(overwrite=True, suffix="Timestamp")),
                     edges=[(0, 1)])
    assert codes(workflow(expr(timer()), expr(group("Log", inner)), edges=[(0, 1)])) == []


def test_filename_from_data_is_not_judged():
    xml = workflow(expr(timer()), expr(property_mapping("FileName")),
                   expr(csv_writer(overwrite=True)), edges=[(0, 2), (1, 2, "Source2")])
    report = baghban.check(baghban.loads(document(xml)))
    assert report.codes() == []
    assert any("assigned from data" in s for s in report.skipped)


def test_externalized_filename_is_downgraded_to_warning():
    xml = workflow(expr(timer()), expr(externalized("FileName")),
                   expr(csv_writer(overwrite=True)), edges=[(0, 2), (1, 2, "Source2")])
    report = baghban.check(baghban.loads(document(xml)))
    assert [(f.code, f.severity) for f in report.findings] == [("SILENT_OVERWRITE", "warning")]


def test_named_pipe_is_not_a_file():
    pipe = ("Combinator", '<Combinator xsi:type="dsp:MatrixWriter"><dsp:Path>\\\\.\\pipe\\x'
            '</dsp:Path><dsp:Suffix>None</dsp:Suffix><dsp:Overwrite>true</dsp:Overwrite>'
            '</Combinator>')
    xml = document(workflow(expr(timer()), expr(pipe), edges=[(0, 1)])).replace(
        'xmlns="https', 'xmlns:dsp="clr-namespace:Bonsai.Dsp;assembly=Bonsai.Dsp" xmlns="https')
    assert baghban.check(baghban.loads(xml)).codes() == []


# ------------------------------------------------------------ FAILS_ON_REPEAT

def test_no_suffix_inside_selectmany_fails_on_second_trial():
    assert codes(single(csv_writer(overwrite=False), in_loop=True)) == ["FAILS_ON_REPEAT"]


def test_timestamp_suffix_inside_selectmany_is_quiet():
    assert codes(single(csv_writer(suffix="Timestamp"), in_loop=True)) == []


def test_defer_is_not_a_loop():
    inner = workflow(expr(workflow_input()), expr(csv_writer()), expr(workflow_output()),
                     edges=[(0, 1), (1, 2)])
    assert codes(workflow(expr(timer()), expr(defer(inner)), edges=[(0, 1)])) == []


# ------------------------------------------------------------ APPENDS_ACROSS_RUNS

def test_append_without_suffix_is_info():
    report = baghban.check(baghban.loads(document(single(csv_writer(append=True, header=True)))))
    assert [(f.code, f.severity) for f in report.findings] == [("APPENDS_ACROSS_RUNS", "info")]
    assert "header" in report.findings[0].message
    assert report.exit_code() == 0


def test_append_with_timestamp_is_quiet():
    assert codes(single(csv_writer(append=True, suffix="Timestamp"))) == []


# ------------------------------------------------------------ DISABLED_WRITER

def test_disabled_writer_fires():
    xml = workflow(expr(camera()), disable(video_writer(suffix="Timestamp")), edges=[(0, 1)])
    assert codes(xml) == ["DISABLED_WRITER"]


def test_writer_inside_disabled_group_fires():
    inner = workflow(expr(workflow_input()), expr(csv_writer(suffix="Timestamp")), edges=[(0, 1)])
    xml = workflow(expr(timer()), disable(group("Logging", inner)), edges=[(0, 1)])
    assert codes(xml) == ["DISABLED_WRITER"]


def test_enabled_writer_is_quiet():
    xml = workflow(expr(camera()), expr(video_writer(suffix="Timestamp")), edges=[(0, 1)])
    assert codes(xml) == []


def test_disabled_writer_is_not_also_an_overwrite():
    xml = workflow(expr(timer()), disable(csv_writer(overwrite=True)), edges=[(0, 1)])
    assert codes(xml) == ["DISABLED_WRITER"]


# ------------------------------------------------------------ DUPLICATE_OUTPUT

def test_two_writers_same_file_fire():
    xml = workflow(expr(timer()), expr(csv_writer("a.csv")), expr(csv_writer("A.CSV")),
                   edges=[(0, 1), (0, 2)])
    assert codes(xml) == ["DUPLICATE_OUTPUT"]


def test_two_writers_different_files_are_quiet():
    xml = workflow(expr(timer()), expr(csv_writer("a.csv")), expr(csv_writer("b.csv")),
                   edges=[(0, 1), (0, 2)])
    assert codes(xml) == []


def test_duplicate_with_disabled_copy_reports_only_the_disabled_one():
    xml = workflow(expr(timer()), expr(csv_writer("a.csv")), disable(csv_writer("a.csv")),
                   edges=[(0, 1), (0, 2)])
    assert codes(xml) == ["DISABLED_WRITER"]


def _module(tmp_path, externalize: bool):
    nodes = [expr(workflow_input()), expr(video_writer("camera.avi"))]
    edges = [(0, 1)]
    if externalize:
        nodes.append(expr(externalized("FileName")))
        edges.append((2, 1, "Source2"))
    (tmp_path / "Recorder.bonsai").write_text(document(workflow(*nodes, edges=edges)))


def test_module_included_twice_writes_one_file(tmp_path):
    _module(tmp_path, externalize=False)
    xml = workflow(expr(camera()), include_expr("Recorder.bonsai"), include_expr("Recorder.bonsai"),
                   edges=[(0, 1), (0, 2)])
    assert codes(xml, tmp_path) == ["DUPLICATE_OUTPUT"]


def test_module_included_twice_with_own_filenames_is_quiet(tmp_path):
    _module(tmp_path, externalize=True)
    xml = workflow(expr(camera()), include_expr("Recorder.bonsai", FileName="left.avi"),
                   include_expr("Recorder.bonsai", FileName="right.avi"),
                   edges=[(0, 1), (0, 2)])
    assert codes(xml, tmp_path) == []


# ------------------------------------------------------------ subjects

def test_subscribe_without_declaration_fires():
    report = baghban.check(baghban.loads(document(workflow(
        expr(timer()), expr(publish("Rewards")), expr(subscribe("Reward")), edges=[(0, 1)]))))
    assert "DANGLING_SUBJECT" in report.codes()
    dangling = next(f for f in report.findings if f.code == "DANGLING_SUBJECT")
    assert "Rewards" in dangling.hint  # near-miss suggestion


def test_subscribe_with_declaration_is_quiet():
    assert codes(workflow(expr(timer()), expr(publish("Trials")), expr(subscribe("Trials")),
                          edges=[(0, 1)])) == []


def test_multicast_without_declaration_fires():
    assert codes(workflow(expr(timer()), expr(multicast("Events")), edges=[(0, 1)])) \
        == ["DANGLING_SUBJECT"]


def test_outer_declaration_is_visible_in_nested_scope():
    inner = workflow(expr(workflow_input()), expr(subscribe("State")), expr(workflow_output()),
                     edges=[(1, 2)])
    xml = workflow(expr(timer()), expr(behavior("State")), expr(select_many(inner)),
                   edges=[(0, 1), (0, 2)])
    assert codes(xml) == []


def test_declaration_inside_group_is_visible_outside():
    # GroupContext forwards declarations to the parent build context
    inner = workflow(expr(workflow_input()), expr(publish("Events")), edges=[(0, 1)])
    xml = workflow(expr(timer()), expr(group("Source", inner)), expr(subscribe("Events")),
                   edges=[(0, 1)])
    assert codes(xml) == []


def test_declaration_inside_selectmany_is_not_visible_outside():
    inner = workflow(expr(workflow_input()), expr(publish("Local")), expr(workflow_output()),
                     edges=[(0, 1), (1, 2)])
    xml = workflow(expr(timer()), expr(select_many(inner)), expr(subscribe("Local")),
                   edges=[(0, 1)])
    report = baghban.check(baghban.loads(document(xml)))
    assert "DANGLING_SUBJECT" in report.codes()
    dangling = next(f for f in report.findings if f.code == "DANGLING_SUBJECT")
    assert "SelectMany" in dangling.message and "nested workflow" in dangling.message


def test_dangling_message_does_not_blame_nesting_without_cause():
    report = baghban.check(baghban.loads(document(workflow(expr(subscribe("Ghost"))))))
    assert "nested" not in report.findings[0].message


def test_disabled_declaration_does_not_declare():
    xml = workflow(expr(timer()), disable(publish("Events")), expr(subscribe("Events")),
                   edges=[(0, 1)])
    assert codes(xml) == ["DANGLING_SUBJECT"]


def test_disabled_subscriber_is_quiet():
    assert codes(workflow(expr(timer()), disable(subscribe("Nothing")))) == []


def test_unreadable_include_silences_subject_checks():
    xml = workflow(include_expr("SomePackage:Module.bonsai"), expr(subscribe("FromModule")))
    report = baghban.check(baghban.loads(document(xml)))
    assert report.codes() == []
    assert any("SomePackage" in s for s in report.skipped)
    assert any("FromModule" in s for s in report.skipped)


def test_same_name_in_one_scope_fires():
    xml = workflow(expr(timer()), expr(publish("X")), expr(timer()), expr(publish("X")),
                   expr(subscribe("X")), edges=[(0, 1), (2, 3)])
    assert codes(xml) == ["DUPLICATE_SUBJECT"]


def test_same_name_in_group_and_parent_fires():
    inner = workflow(expr(workflow_input()), expr(publish("X")), edges=[(0, 1)])
    xml = workflow(expr(timer()), expr(publish("X")), expr(group("G", inner)),
                   expr(subscribe("X")), edges=[(0, 1), (0, 2)])
    assert codes(xml) == ["DUPLICATE_SUBJECT"]


def test_redefinition_in_nested_scope_is_quiet():
    inner = workflow(expr(workflow_input()), expr(publish("X")), expr(subscribe("X")),
                     expr(workflow_output()), edges=[(0, 1), (2, 3)])
    xml = workflow(expr(timer()), expr(publish("X")), expr(subscribe("X")),
                   expr(select_many(inner)), edges=[(0, 1), (2, 3)])
    assert codes(xml) == []


def test_unused_subject_is_info():
    report = baghban.check(baghban.loads(document(workflow(
        expr(timer()), expr(publish("Orphan")), edges=[(0, 1)]))))
    assert [(f.code, f.severity) for f in report.findings] == [("UNUSED_SUBJECT", "info")]


# ------------------------------------------------------------ includes

def test_missing_include_fires(tmp_path):
    assert codes(workflow(include_expr("modules/Nope.bonsai")), tmp_path) == ["MISSING_INCLUDE"]


def test_present_include_is_quiet(tmp_path):
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "Ok.bonsai").write_text(document(workflow(expr(timer()))))
    assert codes(workflow(include_expr("modules/Ok.bonsai")), tmp_path) == []


def test_include_without_extension_gets_bonsai_extension(tmp_path):
    (tmp_path / "Ok.bonsai").write_text(document(workflow(expr(timer()))))
    assert codes(workflow(include_expr("Ok")), tmp_path) == []


def test_windows_backslashes_resolve(tmp_path):
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "Ok.bonsai").write_text(document(workflow(expr(timer()))))
    assert codes(workflow(include_expr("modules\\Ok.bonsai")), tmp_path) == []


def test_nested_includes_resolve_from_top_level_folder(tmp_path):
    # Bonsai opens include paths relative to the working directory (the top-level
    # workflow's folder), not relative to the file that contains the include.
    (tmp_path / "modules").mkdir()
    (tmp_path / "Leaf.bonsai").write_text(document(workflow(expr(timer()))))
    (tmp_path / "modules" / "Mid.bonsai").write_text(document(workflow(include_expr("Leaf.bonsai"))))
    assert codes(workflow(include_expr("modules/Mid.bonsai")), tmp_path) == []


def test_include_cycle_fires(tmp_path):
    (tmp_path / "A.bonsai").write_text(document(workflow(include_expr("B.bonsai"))))
    (tmp_path / "B.bonsai").write_text(document(workflow(include_expr("A.bonsai"))))
    doc = baghban.load(tmp_path / "A.bonsai")
    assert baghban.check(doc).codes() == ["RECURSIVE_INCLUDE"]


def test_disabled_missing_include_is_quiet(tmp_path):
    xml = workflow(expr(timer()), disable(("IncludeWorkflow", "")))
    assert codes(xml, tmp_path) == []


def test_exit_code():
    bad = baghban.check(baghban.loads(document(single(csv_writer(overwrite=True)))))
    good = baghban.check(baghban.loads(document(single(csv_writer(suffix="Timestamp")))))
    assert bad.exit_code() == 1 and good.exit_code() == 0
