"""Module conventions, found by running baghban over published rigs: files in
an Extensions folder or embedded in a package project are modules, whose
undeclared subjects are their interface, not errors."""

import baghban
from baghban.cli import main, select_roots
from baghban.project import discover_projects, repository_root
from xmlkit import (document, expr, externalized, include_expr, publish, select_many, subscribe,
                    timer, workflow, workflow_input, workflow_output)

EMBEDDING = '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><EmbeddedResource Include="**\\*.bonsai" /></ItemGroup></Project>'


def repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_extension_module_expects_subjects_and_resolves_from_project(tmp_path):
    root = repo(tmp_path)
    (root / "Extensions").mkdir()
    (root / "Leaf.bonsai").write_text(document(workflow(expr(timer()))))
    module = root / "Extensions" / "Logger.bonsai"
    module.write_text(document(workflow(expr(subscribe("Events")), include_expr("Leaf.bonsai"))))
    doc = baghban.load(module)
    assert doc.kind == "extension" and doc.base_dir == root
    report = baghban.check(doc)
    assert report.findings == [] and report.interface == ["Events"]
    assert "Checked as Extensions module" in report.summary()


def test_package_module_and_automatic_resource_root(tmp_path):
    root = repo(tmp_path)
    pkg = root / "src" / "My.Package"
    pkg.mkdir(parents=True)
    (pkg / "My.Package.csproj").write_text(EMBEDDING)
    (pkg / "Helper.bonsai").write_text(document(workflow(expr(timer()))))
    module = pkg / "Log.bonsai"
    module.write_text(document(workflow(expr(subscribe("Data")),
                                        include_expr("My.Package:Helper.bonsai"))))
    doc = baghban.load(module)
    assert doc.kind == "package"
    assert doc.workflow.nodes[1].include.status == "ok"  # followed without --resource-root
    report = baghban.check(doc)
    assert report.errors == [] and report.interface == ["Data"]


def test_test_project_fixtures_are_workflows_but_still_resolve(tmp_path):
    root = repo(tmp_path)
    tests = root / "My.Tests"
    tests.mkdir()
    (tests / "My.Tests.csproj").write_text(EMBEDDING)
    (tests / "Inner.bonsai").write_text(document(workflow(expr(timer()))))
    (tests / "Case.bonsai").write_text(document(workflow(
        expr(subscribe("Missing")), include_expr("My.Tests:Inner.bonsai"))))
    doc = baghban.load(tests / "Case.bonsai")
    assert doc.kind == "workflow"
    assert doc.workflow.nodes[1].include.status == "ok"
    assert baghban.check(doc).codes() == ["DANGLING_SUBJECT"]
    assert discover_projects(tests / "Case.bonsai")[0][2] is True


def test_hidden_declaration_is_still_an_error_in_a_module(tmp_path):
    root = repo(tmp_path)
    (root / "Extensions").mkdir()
    inner = workflow(expr(workflow_input()), expr(publish("Local")), expr(workflow_output()),
                     edges=[(0, 1), (1, 2)])
    module = root / "Extensions" / "M.bonsai"
    module.write_text(document(workflow(expr(timer()), expr(select_many(inner)),
                                        expr(subscribe("Local")), edges=[(0, 1)])))
    assert baghban.check(baghban.load(module)).codes() == ["DANGLING_SUBJECT"]


def test_externalized_subject_name_is_set_by_includer():
    xml = workflow(expr(externalized("Name")), expr(("SubscribeSubject", "")),
                   edges=[(0, 1, "Source1")])
    report = baghban.check(baghban.loads(document(xml)))
    assert report.findings == []
    assert any("externalized" in s for s in report.skipped)


def test_top_level_workflow_is_still_strict(tmp_path):
    root = repo(tmp_path)
    wf = root / "main.bonsai"
    wf.write_text(document(workflow(expr(subscribe("Nope")))))
    assert baghban.check(baghban.load(wf)).codes() == ["DANGLING_SUBJECT"]


def test_repository_root_falls_back_to_solution(tmp_path):
    (tmp_path / "Rig.sln").write_text("")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert repository_root(deep / "x.bonsai") == tmp_path


def test_environment_folder_named_dot_bonsai_is_ignored(tmp_path, capsys):
    root = repo(tmp_path)
    (root / ".bonsai").mkdir()
    (root / "sub").mkdir()
    (root / "sub" / ".bonsai").mkdir()  # visible parent, folder itself named .bonsai
    (root / "main.bonsai").write_text(document(workflow(expr(timer()))))
    assert main(["check", str(root)]) == 0
    capsys.readouterr()


def test_include_cycle_members_are_still_checked(tmp_path):
    root = repo(tmp_path)
    (root / "A.bonsai").write_text(document(workflow(include_expr("B.bonsai"))))
    (root / "B.bonsai").write_text(document(workflow(include_expr("A.bonsai"))))
    docs = [baghban.load(root / "A.bonsai"), baghban.load(root / "B.bonsai")]
    roots = select_roots(docs)
    assert len(roots) == 1
    assert baghban.check(roots[0]).codes() == ["RECURSIVE_INCLUDE"]
