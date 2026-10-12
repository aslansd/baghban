"""The --property confirmation kit (confirm/confirm_properties.py) runs real
Bonsai on a Mac; here its predictions and its judgement of outcomes are tested
with simulated runs, so that a "NO" there means Bonsai disagreed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "confirm"))
import confirm_properties as cp  # noqa: E402
from confirm_properties import Run  # noqa: E402

BY_NAME = {c.name: c for c in cp.CASES}
ROWS = "1,2026-01-01T00:00:00.1\n2,2026-01-01T00:00:00.2\n3,2026-01-01T00:00:00.3\n"


def test_every_prediction_matches_its_case(tmp_path):
    for case in cp.CASES:
        folder = tmp_path / case.name
        folder.mkdir()
        assert cp.predict(case, folder) == case.expect, case.name


def test_cases_cover_every_refusal_and_both_routes_into_includes():
    kinds = {c.expect[1] for c in cp.CASES if c.expect[0] == "refuses"}
    assert kinds == {"KeyNotFoundException", "InvalidOperationException"}
    assert sum(c.expect[0] == "writes" for c in cp.CASES) >= 5
    assert any(c.files and c.properties for c in cp.CASES)  # into an include
    assert any(c.files and not c.properties for c in cp.CASES)  # the saved include value


def judge(name, run):
    case = BY_NAME[name]
    case.prediction = case.expect
    return case.observe(run)[0]


def test_writes_judgement():
    assert judge("groups_then_include_then_group", Run(0, "", {"c.csv": ROWS}))
    # the value went to the default instead: not confirmed
    assert not judge("groups_then_include_then_group", Run(0, "", {"noise.csv": ROWS}))
    # an extra file, an empty file, or a failure: not confirmed
    assert not judge("top_level", Run(0, "", {"a.csv": ROWS, "default.csv": ROWS}))
    assert not judge("top_level", Run(0, "", {"a.csv": ""}))
    assert not judge("top_level", Run(1, "KeyNotFoundException: Out", {}))
    assert judge("first_of_two_same_names", Run(0, "", {"z.csv": ROWS, "w2.csv": ROWS}))
    assert not judge("first_of_two_same_names", Run(0, "", {"z.csv": ROWS}))


def test_refusal_judgement():
    assert judge("unknown_name", Run(1, "KeyNotFoundException: The specified property 'Nope' "
                                        "was not found in the workflow.", {}))
    assert not judge("unknown_name", Run(1, "InvalidOperationException: ambiguous", {}))
    assert not judge("unknown_name", Run(0, "", {"default.csv": ROWS}))
    assert judge("ambiguous_group", Run(1, "InvalidOperationException: Rec", {}))
