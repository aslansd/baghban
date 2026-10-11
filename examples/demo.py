"""baghban end to end on an example rig. No Bonsai, Windows or .NET needed.

    python examples/demo.py

rig_v1 is a foraging rig as it might look after a few weeks of edits, with
four faults none of which Bonsai reports before data is lost. rig_v2 is the
same rig fixed.
"""

from pathlib import Path

import baghban

HERE = Path(__file__).parent
v1 = baghban.load(HERE / "rig_v1" / "foraging.bonsai")
v2 = baghban.load(HERE / "rig_v2" / "foraging.bonsai")


def section(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


section("1. What the rig does (baghban show)")
print(baghban.outline(v1))

section("2. What will go wrong (baghban check)")
report = baghban.check(v1)
print(report.summary())

section("3. After the fixes")
print(baghban.check(v2).summary())

section("4. What changed between the two (baghban diff)")
print(baghban.diff(v1, v2).summary())

section("5. Protocol identity for provenance (baghban fingerprint --fields)")
for key, value in baghban.manifest_fields(v2).items():
    print(f"  {key:<50} {value}")

out = HERE / "rig_v1.html"
out.write_text(baghban.html(v1, report), encoding="utf-8")
section(f"6. Drawn with findings highlighted: {out}")
print("Open it in a browser (on a Mac: open examples/rig_v1.html).")
