"""baghban against Bonsai's own test workflows.

The expectations below come from Bonsai's test suite, not from baghban:

* WorkflowRunnerTests runs the *BuildException workflows expecting a build
  error; the cause is a MulticastSubject with no declared subject. The
  *RuntimeException workflows build fine and fail only while running
  (division by zero), which no static check can or should report.
* IncludeWorkflowTests expects IncludeWorkflowSelfOuter to fail to build
  (self-inclusion) and IncludeWorkflowMissing to fail on a missing nested
  include; the other include tests build.
* Build_NestedIncludeWorkflows_EnsureInnerPropertyIsAssigned expects the
  outer include's OuterCount (2) to reach the inner workflow's Take.Count.
* MissingTypes references a type that does not exist. baghban has no type
  catalogue, so it must stay quiet rather than guess.
"""

from pathlib import Path

import pytest

import baghban

ROOT = Path(__file__).parent / "data" / "bonsai_upstream"
CORE = ROOT / "Bonsai.Core.Tests"
EDITOR = ROOT / "Bonsai.Editor.Tests"
RESOURCES = {"Bonsai.Core.Tests": CORE, "Bonsai.Editor.Tests": EDITOR}

EXPECTED_ERRORS = {
    EDITOR / "NestedWorkflowBuildException.bonsai": ["DANGLING_SUBJECT"],
    EDITOR / "IncludeWorkflowBuildException.bonsai": ["DANGLING_SUBJECT"],
    EDITOR / "IncludeEmbeddedWorkflowBuildException.bonsai": ["DANGLING_SUBJECT"],
    EDITOR / "MissingSubject.bonsai": ["DANGLING_SUBJECT"],
    CORE / "IncludeWorkflowSelfOuter.bonsai": ["RECURSIVE_INCLUDE"],
    CORE / "IncludeWorkflowSelfInner.bonsai": ["RECURSIVE_INCLUDE"],
    CORE / "IncludeWorkflowMissing.bonsai": ["MISSING_INCLUDE"],
    CORE / "IncludeWorkflowMissingOuter.bonsai": ["MISSING_INCLUDE"],
}

ALL = sorted(ROOT.rglob("*.bonsai"))


def errors(path):
    report = baghban.check(baghban.load(path, resource_roots=RESOURCES))
    return [f.code for f in report.errors]


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.name)
def test_agrees_with_bonsai_test_suite(path):
    assert errors(path) == EXPECTED_ERRORS.get(path, [])


def test_every_expected_file_exists():
    assert all(p.exists() for p in EXPECTED_ERRORS)
    assert len(ALL) >= 30


@pytest.mark.parametrize("name", ["NestedWorkflowRuntimeException.bonsai",
                                  "IncludeWorkflowRuntimeException.bonsai",
                                  "MissingTypes.bonsai"])
def test_stays_quiet_on_what_it_cannot_know(name):
    report = baghban.check(baghban.load(EDITOR / name, resource_roots=RESOURCES))
    assert report.findings == []


def test_nested_include_property_reaches_inner_workflow():
    doc = baghban.load(CORE / "IncludeWorkflow.bonsai", resource_roots=RESOURCES)
    take = next(n for n in doc.walk() if n.type.name == "Take")
    assert take.properties["Count"] == "2"


def test_embedded_include_without_resource_root_is_skipped_not_guessed():
    report = baghban.check(baghban.load(CORE / "IncludeWorkflowMissing.bonsai"))
    assert report.findings == []
    assert len(report.skipped) == 1 and "--resource-root" in report.skipped[0]


def test_closest_redefinition_resolves_to_inner_subject():
    doc = baghban.load(EDITOR / "NestedSubscribeSubjectWithClosestRedefinition.bonsai")
    assert baghban.check(doc).codes() == []
