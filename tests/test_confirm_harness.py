"""The confirmation harness (confirm/confirm.py) runs real Bonsai on a Mac; here
its predictions and its judgement of outcomes are tested with simulated runs,
so that a "NO" on a real machine means Bonsai disagreed, not a harness bug."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "confirm"))
import confirm  # noqa: E402
from confirm import Run  # noqa: E402

BY_NAME = {c.name: c for c in confirm.CASES}
T1 = "1,2026-01-01T00:00:00.1\n2,2026-01-01T00:00:00.2\n3,2026-01-01T00:00:00.3\n"
T2 = T1.replace("2026-01-01", "2026-01-02")


def test_every_prediction_matches_its_case():
    for case in confirm.CASES:
        assert confirm.predict(case) == sorted(case.predicts), case.name


def test_each_finding_has_a_quiet_twin_or_a_build_outcome():
    codes = {c for case in confirm.CASES for c in case.predicts}
    assert {"SILENT_OVERWRITE", "FAILS_ON_REPEAT", "DUPLICATE_OUTPUT", "DISABLED_WRITER",
            "APPENDS_ACROSS_RUNS", "DANGLING_SUBJECT", "UNNAMED_SUBJECT"} <= codes
    assert sum(1 for c in confirm.CASES if not c.predicts) >= 4


def judge(name, runs):
    return BY_NAME[name].observe(runs)[0]


def test_overwrite_judgement():
    assert judge("overwrite_across_runs", [Run(0, "", {"data.csv": T1}), Run(0, "", {"data.csv": T2})])
    # if Bonsai had kept both, the finding would not be confirmed
    assert not judge("overwrite_across_runs",
                     [Run(0, "", {"data.csv": T1}), Run(0, "", {"data.csv": T1, "data2.csv": T2})])


def test_per_element_judgement():
    assert judge("overwrite_per_element", [Run(0, "", {"trial.csv": "3,x\n"})])
    assert not judge("overwrite_per_element", [Run(0, "", {"trial.csv": T1})])
    assert judge("writer_after_loop", [Run(0, "", {"trials.csv": T1})])


def test_failure_judgements():
    err = "IOException: The file 'trial.csv' already exists."
    assert judge("fails_on_repeat", [Run(1, err, {"trial.csv": "1,x\n"})])
    assert not judge("fails_on_repeat", [Run(0, "", {"trial.csv": T1})])
    assert judge("no_overwrite_second_run_stops",
                 [Run(0, "", {"data.csv": T1}), Run(1, "IOException: The file 'data.csv' already exists.", {"data.csv": T1})])
    assert judge("dangling_subject", [Run(1, "WorkflowBuildException: ...", {})])


def test_other_judgements():
    assert judge("duplicate_output", [Run(1, "IOException: used by another process", {"same.csv": T1})])
    assert not judge("duplicate_output", [Run(0, "", {"same.csv": T1 + T1})])
    assert judge("distinct_outputs", [Run(0, "", {"a.csv": T1, "b.csv": T1})])
    assert judge("disabled_writer", [Run(0, "", {})])
    assert judge("appends_across_runs", [Run(0, "", {"data.csv": T1}), Run(0, "", {"data.csv": T1 + T2})])
    assert judge("unnamed_subscribe", [Run(0, "", {"out.csv": ""})])
    assert judge("overwrite_with_timestamp_suffix",
                 [Run(0, "", {"a.csv": T1}), Run(0, "", {"a.csv": T1, "b.csv": T2})])
