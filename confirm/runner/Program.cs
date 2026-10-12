// Same steps as Bonsai.Player/Program.cs: deserialize, build, run to completion.
// Exit 0 when the workflow completes, 1 on any build or runtime exception,
// with the exception printed on stderr so confirm.py can read it.
//
// NAME=VALUE arguments after the workflow are applied as Bonsai.exe applies
// --property NAME=VALUE (Bonsai.Editor/WorkflowRunner.cs, BuildAssignProperties):
// build the workflow, then SetWorkflowProperty for each, in order, then run.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reactive.Linq;
using System.Threading.Tasks;
using System.Xml;
using Bonsai;
using Bonsai.Expressions;

class Program
{
    static async Task<int> Main(string[] args)
    {
        if (args.Length < 1 || !File.Exists(args[0]))
        {
            Console.Error.WriteLine("usage: BaghbanRunner WORKFLOW [NAME=VALUE ...]");
            return 2;
        }
        var assignments = new List<KeyValuePair<string, string>>();
        for (int i = 1; i < args.Length; i++)
        {
            var parts = args[i].Split(new[] { '=' }, 2);
            if (parts.Length != 2)
            {
                Console.Error.WriteLine($"expected NAME=VALUE, got '{args[i]}'");
                return 2;
            }
            assignments.Add(new KeyValuePair<string, string>(parts[0], parts[1]));
        }
        try
        {
            WorkflowBuilder builder;
            using (var reader = XmlReader.Create(args[0]))
            {
                builder = (WorkflowBuilder)WorkflowBuilder.Serializer.Deserialize(reader);
            }
            if (assignments.Count > 0)
            {
                builder.Workflow.Build();
                foreach (var assignment in assignments)
                {
                    builder.Workflow.SetWorkflowProperty(assignment.Key, assignment.Value);
                }
            }
            // LastOrDefaultAsync: a workflow that completes without values is not an error
            await builder.Workflow.BuildObservable().LastOrDefaultAsync();
            // Bonsai's file writers (CsvWriter, FileSink) write and close their files on a
            // background EventLoopScheduler (Bonsai.System/IO/WriterDisposable.cs). When the
            // workflow completes, closing is only *scheduled*; exiting now would kill that
            // thread before it flushes, leaving empty files. The editor never exits here, so
            // give the writers time to finish, as a running Bonsai would.
            await Task.Delay(TimeSpan.FromSeconds(2));
            return 0;
        }
        catch (Exception ex)
        {
            var inner = ex;
            while (inner.InnerException != null) inner = inner.InnerException;
            Console.Error.WriteLine($"{inner.GetType().Name}: {inner.Message}");
            return 1;
        }
    }
}
