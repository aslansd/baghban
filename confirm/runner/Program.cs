// Same steps as Bonsai.Player/Program.cs: deserialize, build, run to completion.
// Exit 0 when the workflow completes, 1 on any build or runtime exception,
// with the exception printed on stderr so confirm.py can read it.
using System;
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
        if (args.Length != 1 || !File.Exists(args[0]))
        {
            Console.Error.WriteLine("usage: BaghbanRunner WORKFLOW");
            return 2;
        }
        try
        {
            WorkflowBuilder builder;
            using (var reader = XmlReader.Create(args[0]))
            {
                builder = (WorkflowBuilder)WorkflowBuilder.Serializer.Deserialize(reader);
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
