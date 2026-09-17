using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Linq;
using System.Text;
using VirtualLabAPI.Core.Materials;

namespace VlCatalogInspector
{
    internal static class Program
    {
        private static int Main(string[] args)
        {
            string installDir = null;
            string outDir = null;

            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i];
                if (a == "--install-dir")
                {
                    if (i + 1 >= args.Length) return Usage("missing value for --install-dir");
                    installDir = args[++i].Trim('"');
                }
                else if (a == "--out")
                {
                    if (i + 1 >= args.Length) return Usage("missing value for --out");
                    outDir = args[++i].Trim('"');
                }
                else if (a == "--help" || a == "-h")
                    return Usage(null);
                else
                    return Usage("unknown argument: " + a);
            }

            if (string.IsNullOrWhiteSpace(installDir))
                return Usage("--install-dir is required");
            if (string.IsNullOrWhiteSpace(outDir))
                return Usage("--out is required");

            installDir = Path.GetFullPath(installDir);
            outDir = Path.GetFullPath(outDir);
            if (!Directory.Exists(installDir))
            {
                Console.Error.WriteLine("error: install-dir not found: " + installDir);
                return 1;
            }
            Directory.CreateDirectory(outDir);

            LicenseManager.CurrentContext = new DesignTimeLicenseContext();
            try { Directory.SetCurrentDirectory(installDir); }
            catch (Exception ex)
            {
                Console.Error.WriteLine("error: SetCurrentDirectory failed: " + ex.Message);
                return 1;
            }

            string failListPath = Path.Combine(outDir, "_export_log", "material_fail.txt");
            string notesDir = Path.Combine(outDir, "_export_log");

            int matOk, matFail;
            int matExit = LiveMaterialExport.Run(installDir, outDir, failListPath, out matOk, out matFail);
            if (matExit != 0)
                return matExit;

            // Rebuild name→dir map for films $ref resolution.
            MaterialsCatalog catalog = CatalogLoader.LoadMaterialsCatalog(installDir);
            StandardMaterial[] entries = catalog.Entries.Cast<StandardMaterial>().ToArray();
            Dictionary<string, string> dirNames = TagLayout.UniqueDirNames(entries.Select(m => m.Name));
            var nameToDir = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var kv in dirNames) nameToDir[kv.Key] = kv.Value;

            var failLines = new List<string>();
            if (File.Exists(failListPath))
                failLines.AddRange(File.ReadAllLines(failListPath, Encoding.UTF8));

            int filmOk, filmFail;
            LiveFilmsExport.Run(installDir, outDir, nameToDir, failLines, out filmOk, out filmFail);

            int gOk, gSkip;
            LiveGeometryExport.Run(installDir, outDir, notesDir, out gOk, out gSkip);

            Directory.CreateDirectory(Path.GetDirectoryName(failListPath) ?? outDir);
            File.WriteAllLines(failListPath, failLines.ToArray(), new UTF8Encoding(false));

            Console.WriteLine(
                "VlCatalogInspector: materials ok={0} fail={1}; films ok={2} fail={3}; geometries ok={4} skip={5}",
                matOk, matFail, filmOk, filmFail, gOk, gSkip);

            if (matOk == 0) return 1;
            if (filmFail > 0) return 1;
            return 0;
        }

        private static int Usage(string error)
        {
            if (!string.IsNullOrEmpty(error))
                Console.Error.WriteLine("error: " + error);
            Console.Error.WriteLine(
                "usage: VlCatalogInspector --install-dir <VL_ROOT> --out <database_virtuallab_root>");
            return 2;
        }
    }

    internal sealed class DesignTimeLicenseContext : LicenseContext
    {
        public override LicenseUsageMode UsageMode
        {
            get { return LicenseUsageMode.Designtime; }
        }
    }
}
