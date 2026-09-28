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
