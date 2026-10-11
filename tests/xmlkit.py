"""Build .bonsai XML for tests, in the exact shape Bonsai's XmlSerializer writes.

A *builder* is a (xsi_type, body) pair. ``expr`` wraps it in <Expression>,
``disable`` in <Expression xsi:type="Disable"><Builder>, so the same operator
can be tested enabled and disabled.
"""

HEADER = """<?xml version="1.0" encoding="utf-8"?>
<WorkflowBuilder Version="2.9.0"
                 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                 xmlns:rx="clr-namespace:Bonsai.Reactive;assembly=Bonsai.Core"
                 xmlns:io="clr-namespace:Bonsai.IO;assembly=Bonsai.System"
                 xmlns:cv="clr-namespace:Bonsai.Vision;assembly=Bonsai.Vision"
                 xmlns="https://bonsai-rx.org/2018/workflow">
"""


def document(workflow: str) -> str:
    return HEADER + f"  <Workflow>{workflow}</Workflow>\n</WorkflowBuilder>\n"


def workflow(*nodes: str, edges=()) -> str:
    edge_xml = "".join(f'<Edge From="{a}" To="{b}" Label="{label}" />'
                       for a, b, *rest in edges for label in [rest[0] if rest else "Source1"])
    return f"<Nodes>{''.join(nodes)}</Nodes><Edges>{edge_xml}</Edges>"


def expr(builder) -> str:
    xtype, body = builder
    return f'<Expression xsi:type="{xtype}">{body}</Expression>'


def disable(builder) -> str:
    xtype, body = builder
    return f'<Expression xsi:type="Disable"><Builder xsi:type="{xtype}">{body}</Builder></Expression>'


# ---------------------------------------------------------------- builders

def combinator(xtype: str, body: str = ""):
    return ("Combinator", f'<Combinator xsi:type="{xtype}">{body}</Combinator>')


def timer(period="PT1S"):
    return combinator("rx:Timer", f"<rx:DueTime>PT0S</rx:DueTime><rx:Period>{period}</rx:Period>")


def csv_writer(filename="data.csv", overwrite=False, suffix="None", append=False, header=False):
    return ("io:CsvWriter",
            f"<io:FileName>{filename}</io:FileName><io:Append>{str(append).lower()}</io:Append>"
            f"<io:Overwrite>{str(overwrite).lower()}</io:Overwrite><io:Suffix>{suffix}</io:Suffix>"
            f"<io:IncludeHeader>{str(header).lower()}</io:IncludeHeader>")


def video_writer(filename="video.avi", overwrite=False, suffix="None"):
    return combinator("cv:VideoWriter",
                      f"<cv:FileName>{filename}</cv:FileName><cv:Suffix>{suffix}</cv:Suffix>"
                      f"<cv:Buffered>true</cv:Buffered><cv:Overwrite>{str(overwrite).lower()}</cv:Overwrite>"
                      "<cv:FourCC>FMP4</cv:FourCC><cv:FrameRate>30</cv:FrameRate>")


def camera():
    return combinator("cv:CameraCapture", "<cv:Index>0</cv:Index>")


def publish(name):
    return ("rx:PublishSubject", f"<Name>{name}</Name>")


def behavior(name):
    return ("rx:BehaviorSubject", f"<Name>{name}</Name>")


def subscribe(name):
    return ("SubscribeSubject", f"<Name>{name}</Name>")


def multicast(name):
    return ("MulticastSubject", f"<Name>{name}</Name>")


def group(name, inner):
    return ("GroupWorkflow", f"<Name>{name}</Name><Workflow>{inner}</Workflow>")


def select_many(inner):
    return ("rx:SelectMany", f"<Workflow>{inner}</Workflow>")


def defer(inner):
    return ("rx:Defer", f"<Workflow>{inner}</Workflow>")


def include_expr(path, **overrides) -> str:
    body = "".join(f"<{k}>{v}</{k}>" for k, v in overrides.items())
    return f'<Expression xsi:type="IncludeWorkflow" Path="{path}">{body}</Expression>'


def externalized(*names):
    props = "".join(f'<Property Name="{n}" />' if isinstance(n, str)
                    else f'<Property Name="{n[0]}" DisplayName="{n[1]}" />' for n in names)
    return ("ExternalizedMapping", props)


def property_mapping(*names):
    props = "".join(f'<Property Name="{n}" />' for n in names)
    return ("PropertyMapping", f"<PropertyMappings>{props}</PropertyMappings>")


def workflow_input():
    return ("WorkflowInput", "<Name>Source1</Name>")


def workflow_output():
    return ("WorkflowOutput", "")
