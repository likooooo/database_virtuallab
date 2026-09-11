using System.Collections.Generic;
using System.IO;

namespace VlCatalogInspector
{
    internal static class TreeUtil
    {
        public static void ClearMaterialsTree(string outRoot)
        {
            ClearYmlTree(Path.Combine(outRoot, "materials"));
        }

        public static void ClearYmlTree(string root)
        {
            if (!Directory.Exists(root)) return;
            foreach (string f in Directory.GetFiles(root, "*.yml", SearchOption.AllDirectories))
                File.Delete(f);
            foreach (string f in Directory.GetFiles(root, "*.yaml", SearchOption.AllDirectories))
                File.Delete(f);
        }
    }
}
