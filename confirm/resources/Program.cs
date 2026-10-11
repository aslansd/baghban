// For each assembly path given, print its name and every manifest resource
// (name, offset, whether it is embedded, SHA-256 of its bytes) as JSON, read
// with System.Reflection.Metadata. The assembly is only read, never loaded.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;

class Program
{
    static int Main(string[] args)
    {
        var results = new List<object>();
        foreach (var path in args)
        {
            try
            {
                using var stream = File.OpenRead(path);
                using var pe = new PEReader(stream);
                if (!pe.HasMetadata)
                {
                    results.Add(new { path, error = "no .NET metadata" });
                    continue;
                }
                var md = pe.GetMetadataReader();
                string assembly = md.IsAssembly ? md.GetString(md.GetAssemblyDefinition().Name) : null;
                var resources = new List<object>();
                foreach (var handle in md.ManifestResources)
                {
                    var res = md.GetManifestResource(handle);
                    bool embedded = res.Implementation.IsNil;
                    string sha256 = null;
                    if (embedded)
                    {
                        int rva = pe.PEHeaders.CorHeader.ResourcesDirectory.RelativeVirtualAddress;
                        var block = pe.GetSectionData(rva);
                        var reader = block.GetReader((int)res.Offset, block.Length - (int)res.Offset);
                        int length = reader.ReadInt32();
                        byte[] bytes = reader.ReadBytes(length);
                        sha256 = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
                    }
                    resources.Add(new { name = md.GetString(res.Name), offset = res.Offset, embedded, sha256 });
                }
                results.Add(new { path, assembly, resources });
            }
            catch (Exception ex)
            {
                results.Add(new { path, error = ex.GetType().Name + ": " + ex.Message });
            }
        }
        Console.WriteLine(JsonSerializer.Serialize(results));
        return 0;
    }
}
