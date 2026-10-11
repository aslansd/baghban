# Bonsai's own test workflows

Copied unchanged from the Bonsai repository (github.com/bonsai-rx/bonsai,
commit ba3abbcb07d7f64aff63aca613587a71858bd806), folders
`Bonsai.Core.Tests/` and `Bonsai.Editor.Tests/`. MIT licence; see `LICENSE`
in this folder.

They are used as ground truth that does not depend on baghban: Bonsai's
own test suite (`IncludeWorkflowTests.cs`, `WorkflowRunnerTests.cs`) asserts
which of these workflows fail to build and which build fine, and what value
a nested include property takes. `tests/test_ground_truth.py` checks that
baghban agrees.
