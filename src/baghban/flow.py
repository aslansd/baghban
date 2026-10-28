"""How many elements reach a node: just enough to tell when a loop runs once.

A writer inside a ``SelectMany`` is opened once for every element the loop
receives. When the XML shows that the loop receives at most one element per
run, the writer is opened once per run, like any writer outside a loop. iblrig
does this: its stimulus loops are fed by chains that end in ``LastOrDefault``
or a ``Timer`` with no period.

The question asked of each node is narrow: does its output carry **at most
one element per subscription of its workflow**? The answer is yes only when
every step is an operator whose behaviour was read in the Bonsai source
(Bonsai.Core, Bonsai.Shaders) and is listed below. Anything else, including
subjects, multiple data inputs, disabled nodes and third-party operators,
answers "not known", which keeps the loop a loop. So a mistake here can only
leave an error in place; it cannot hide one, unless an operator below is
listed wrongly.

* **At most one, whatever comes in:** ``First``, ``FirstOrDefault``,
  ``Last``, ``LastOrDefault`` (``FirstAsync`` and friends); ``Take`` and
  ``TakeLast`` with ``Count`` 0 or 1; the aggregates ``Count``, ``Sum``,
  ``Average``, ``Min``, ``Max``, ``IsEmpty``, ``ToArray``, ``ToList``;
  ``Timer`` (Bonsai.Reactive and Bonsai.Shaders) with no ``Period``, or a
  ``Period`` of zero ("the timer will only fire once"); ``Unit`` with no
  input (``Observable.Return``). A property source *without* input does not
  count: it emits again whenever the property changes.
* **No more than their input:** filters, delays and pass-throughs (``Skip*``,
  ``Take*``, ``Distinct*``, ``Delay``, ``DelaySubscription``, ``Throttle``,
  ``ObserveOn``, ``SubscribeOn``, ``Synchronize``, ``IgnoreElements``,
  ``MulticastSubject``, which is ``source.Do(subject)``, file writers, the
  nested ``Condition`` and ``Sink``); one-for-one maps (``Timestamp``,
  ``TimeInterval``, ``Index``, ``Unit``, property sources with an input,
  which are ``source.Select(x => value)``); and, by their first input,
  ``TakeUntil``, ``SkipUntil``, ``SubscribeWhen``, ``WithLatestFrom``.
  ``Zip`` emits no more than its smallest input.
* **Nested workflows:** a group, an include, ``Defer`` and ``NestedWorkflow``
  (a ``Defer``) give their workflow their own input and emit what it outputs.
  ``SelectMany`` gives its workflow one element at a time
  (``Observable.Return(element)``) and emits what that outputs, per element.
  The exception is elements that are themselves observables (from ``Window``,
  ``GroupBy``, ``CreateObservable``...), which ``SelectMany`` passes in
  whole. So an element baghban cannot show is not an observable makes its
  inner input "not known".

A loop that runs once must also not be re-subscribed: ``Repeat``,
``RepeatCount``, ``Retry`` or ``RetryCount`` downstream of it, or downstream
of anything that contains it, would run it again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .model import Node, Workflow

_MAPPINGS = {"ExternalizedMapping", "PropertyMapping", "InputMapping"}
_SHADERS = "Bonsai.Shaders"

AT_MOST_ONE_SAME = {"First", "FirstOrDefault", "Last", "LastOrDefault"}
AT_MOST_ONE_NEW = {"Count", "Sum", "Average", "Min", "Max", "IsEmpty", "ToArray", "ToList"}
NOT_MORE = {"Skip", "SkipLast", "SkipWhile", "Take", "TakeLast", "TakeWhile", "Distinct",
            "DistinctBy", "DistinctUntilChanged", "DistinctUntilChangedBy", "Delay",
            "DelaySubscription", "Throttle", "ObserveOn", "SubscribeOn", "Synchronize",
            "IgnoreElements", "MulticastSubject", "Condition", "Sink"}
ONE_FOR_ONE_NEW = {"Timestamp", "TimeInterval", "Index", "Unit"}
BY_FIRST_INPUT = {"TakeUntil", "SkipUntil", "SubscribeWhen", "WithLatestFrom"}
HIGHER_ORDER = {"Window", "WindowCount", "WindowTime", "WindowTrigger", "GroupBy",
                "CreateObservable", "WindowWorkflow"}
TRANSPARENT = {"GroupWorkflow", "IncludeWorkflow", "Defer", "NestedWorkflow"}
PROPERTY_SOURCES = {"BooleanProperty", "ByteProperty", "DateTimeOffsetProperty", "DateTimeProperty",
                    "DoubleProperty", "FloatProperty", "Int64Property", "IntProperty",
                    "StringProperty", "TimeSpanProperty"}
RESUBSCRIBE = {"Repeat", "RepeatCount", "Retry", "RetryCount"}


@dataclass(frozen=True)
class Flow:
    """What reaches a node per subscription of its workflow."""

    one: bool  # at most one element
    scalar: bool  # the elements are certainly not observables
    why: str = ""  # the node that bounds it, for messages


MANY = Flow(False, False)


def _core(node: Node, *names: str) -> bool:
    return node.type.is_core(*names)


def _shaders(node: Node, *names: str) -> bool:
    return node.type.name in names and node.type.namespace == _SHADERS


def _int(value: Optional[str]) -> Optional[int]:
    try:
        return int((value or "").strip())
    except ValueError:
        return None


def _no_period(node: Node) -> bool:
    period = (node.properties.get("Period") or "").strip()
    return period in ("", "PT0S", "P0D", "-PT0S")


def data_inputs(node: Node) -> list:
    """Predecessors that carry data, ordered by edge label (Source1 first);
    mappings, which set properties, are left out."""
    wf = node.parent
    out = []
    for e in wf.edges:
        if e.target == node.index and 0 <= e.source < len(wf.nodes):
            src = wf.nodes[e.source]
            if not _core(src, *_MAPPINGS):
                out.append((e.label, src))
    out.sort(key=lambda p: (len(p[0]), p[0]))
    return [src for _, src in out]


class FlowAnalysis:
    """Memoised over one document; nodes are compared by identity."""

    def __init__(self):
        self._flows: dict = {}
        self._inputs: dict = {}

    # -- workflow inputs -----------------------------------------------------
    def workflow_input(self, wf: Workflow) -> Flow:
        key = id(wf)
        if key not in self._inputs:
            self._inputs[key] = MANY  # guards against cycles
            self._inputs[key] = self._workflow_input(wf)
        return self._inputs[key]

    def _workflow_input(self, wf: Workflow) -> Flow:
        owner = wf.owner
        if owner is None or owner.disabled:
            return MANY  # a top-level input: whatever the includer sends
        inputs = data_inputs(owner)
        source = self.flow(inputs[0]) if len(inputs) == 1 else (MANY if inputs else None)
        if _core(owner, "SelectMany"):
            if source is None:
                return MANY
            if source.scalar:
                return Flow(True, False, f"{owner.label()} passes in one element at a time")
            return MANY
        if _core(owner, *TRANSPARENT, "Sink", "Condition"):
            return source if source is not None else MANY
        return MANY

    # -- nodes ---------------------------------------------------------------
    def flow(self, node: Node) -> Flow:
        key = id(node)
        if key not in self._flows:
            self._flows[key] = MANY  # guards against cycles
            self._flows[key] = self._flow(node)
        return self._flows[key]

    def output_of(self, wf: Optional[Workflow]) -> Flow:
        if wf is None:
            return MANY
        outs = [n for n in wf.nodes if _core(n, "WorkflowOutput") and not n.disabled]
        if len(outs) != 1:
            return MANY
        inputs = data_inputs(outs[0])
        return self.flow(inputs[0]) if len(inputs) == 1 else MANY

    def _flow(self, node: Node) -> Flow:
        if node.disabled:
            return MANY
        inputs = data_inputs(node)
        here = node.location()

        if _core(node, "WorkflowInput"):
            return self.workflow_input(node.parent)
        # sources that emit once: only without a data input (with one, a Source
        # runs again for each input element)
        if not inputs:
            if _core(node, "Timer") or _shaders(node, "Timer"):
                # fires once without a period; either way its elements are numbers
                return Flow(_no_period(node), True, here if _no_period(node) else "")
            if _core(node, "Unit"):
                return Flow(True, True, here)
            if _core(node, *PROPERTY_SOURCES):
                return Flow(False, True)  # re-emits whenever the property changes
            if _core(node, *TRANSPARENT):
                return self.output_of(node.workflow)
            return MANY
        if _core(node, *HIGHER_ORDER):
            return MANY

        if _core(node, *BY_FIRST_INPUT):
            first = self.flow(inputs[0])
            return Flow(first.one, True if _core(node, "WithLatestFrom") else first.scalar,
                        first.why)
        if _core(node, "Zip") and len(inputs) >= 2:
            ones = [f for f in map(self.flow, inputs) if f.one]
            return Flow(True, True, ones[0].why) if ones else MANY
        if len(inputs) != 1:
            return MANY  # Merge, CombineLatest, Concat, ...: could be more

        source = self.flow(inputs[0])
        count = _int(node.properties.get("Count"))
        if _core(node, *AT_MOST_ONE_SAME) or (_core(node, "Take", "TakeLast")
                                              and count is not None and count <= 1):
            return Flow(True, source.scalar, here)
        if _core(node, *AT_MOST_ONE_NEW):
            return Flow(True, True, here)
        if _core(node, *NOT_MORE) or _shaders(node, "Delay", "DelaySubscription") \
                or node.is_writer:
            return source
        if _core(node, *ONE_FOR_ONE_NEW, *PROPERTY_SOURCES):
            return Flow(source.one, True, source.why)
        if _core(node, "SelectMany"):
            inner = self.output_of(node.workflow)
            return Flow(source.one and inner.one, inner.scalar, source.why)
        if _core(node, *TRANSPARENT):
            return self.output_of(node.workflow)
        return MANY


def _resubscribed_after(node: Node) -> Optional[Node]:
    """A Repeat/Retry downstream of ``node`` in its own workflow, if any."""
    seen, todo = set(), list(node.successors())
    while todo:
        n = todo.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        if _core(n, *RESUBSCRIBE) and not n.disabled:
            return n
        todo.extend(n.successors())
    return None


def runs_once(node: Node, analysis: Optional[FlowAnalysis] = None) -> tuple:
    """``(True, [(loop, bound), ...])`` when every loop around ``node`` is shown
    to receive at most one element per run (``bound`` is the node that limits
    it) and nothing re-subscribes it; else ``(False, [])``."""
    from .model import REPEATING
    analysis = analysis or FlowAnalysis()
    loops = []
    for container in node.containers():
        if not container.type.is_core(*REPEATING):
            continue
        if not _core(container, "SelectMany"):
            return False, []
        inputs = data_inputs(container)
        if len(inputs) != 1:
            return False, []
        f = analysis.flow(inputs[0])
        if not f.one:
            return False, []
        loops.append((container, f.why))
    for n in [node] + node.containers():
        if _resubscribed_after(n) is not None:
            return False, []
    return True, loops
