using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;

namespace VlCatalogInspector
{
    /// <summary>Live CoatingsCatalog → films YAML (same payload shape as former dump exporter).</summary>
    internal static class LiveFilmsExport
    {
        public static int Run(
            string installDir,
            string outRoot,
            IDictionary<string, string> nameToDir,
            List<string> failLines,
            out int filmOk,
            out int filmFail)
        {
            filmOk = 0;
            filmFail = 0;
            CatalogSlice slice = CatalogLoader.LoadCoatings(installDir);
            TreeUtil.ClearYmlTree(Path.Combine(outRoot, "films"));

            var used = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < slice.Entries.Length; i++)
            {
                object entry = slice.Entries[i];
                string rawName = (i < slice.Names.Length) ? slice.Names[i] : "coating_" + i;
                string stem = TagLayout.SafeDirName(rawName);
                string candidate = stem;
                int n = 2;
                while (!used.Add(candidate))
                {
                    candidate = stem + "_" + n.ToString(CultureInfo.InvariantCulture);
                    n++;
                }
                stem = candidate;
                try
                {
                    WriteFilm(entry, rawName, stem, outRoot, nameToDir);
                    filmOk++;
                }
                catch (Exception ex)
                {
                    filmFail++;
                    failLines.Add("film\t" + stem + "\t" + Unwrap(ex).Message);
                }
            }
            Console.WriteLine("live films: ok={0} fail={1} of {2}", filmOk, filmFail, slice.Entries.Length);
            return filmFail;
        }

        private static void WriteFilm(
            object entry, string rawName, string stem, string outRoot, IDictionary<string, string> nameToDir)
        {
            IEnumerable catsEnum = null;
            try
            {
                object cats = GetProp(entry, "Categories");
                catsEnum = cats as IEnumerable;
            }
            catch { }
            var catList = new List<string>();
            if (catsEnum != null)
            {
                foreach (object c in catsEnum)
                {
                    if (c == null) continue;
                    string s = Convert.ToString(c, CultureInfo.InvariantCulture);
                    if (!string.IsNullOrWhiteSpace(s)) catList.Add(s);
                }
            }
            List<string> tags = TagLayout.BuildTags(catList, "Solid", keepUnmappedCategory: true);
            string key = TagLayout.ObjectKey(stem);

            object layerListObj = GetProp(entry, "LayerList");
            if (layerListObj == null)
                throw new InvalidOperationException("missing LayerList");
            var layersOut = new List<object>();
            foreach (object layerObj in AsEnumerable(layerListObj))
            {
                if (layerObj == null) continue;
                double thicknessM = RequireDouble(GetProp(layerObj, "Thickness"), "Thickness");
                if (thicknessM < 0)
                    throw new InvalidOperationException("negative Thickness");
                double depthUm = thicknessM * 1e6;
                object medium = GetProp(layerObj, "Medium");
                if (medium == null)
                    throw new InvalidOperationException("layer missing Medium");
                object baseMat = GetProp(medium, "BaseMaterial");
                if (baseMat == null)
                    throw new InvalidOperationException("layer missing BaseMaterial");
                string matName = Convert.ToString(GetProp(baseMat, "Name"), CultureInfo.InvariantCulture);
                if (string.IsNullOrEmpty(matName))
                    throw new InvalidOperationException("layer missing BaseMaterial.Name");
                string dir;
                if (!nameToDir.TryGetValue(matName, out dir))
                    throw new InvalidOperationException("material not in materials catalog: " + matName);
                string matKey = TagLayout.ObjectKey(dir);
                layersOut.Add(new Dictionary<string, object>
                {
                    { "type", "coating" },
                    { "depth", depthUm },
                    { "background_material", new Dictionary<string, object> { { "$ref", matKey } } },
                    { "is_incoherent", false },
                });
            }
            if (layersOut.Count == 0)
                throw new InvalidOperationException("empty LayerList");

            var payload = new Dictionary<string, object>
            {
                { "type", "films" },
                { "layers", layersOut },
            };
            string primary = TagLayout.PrimaryTag(tags);
            string outPath = Path.Combine(outRoot, "films", primary, TagLayout.KeySafeStem(stem) + ".yml");
            YamlWriter.WriteObject(outPath, tags, "", "VirtualLab coating: " + rawName, "", payload, key, null);
        }

        private static IEnumerable AsEnumerable(object o)
        {
            if (o is string) yield break;
            var en = o as IEnumerable;
            if (en == null) yield break;
            foreach (object item in en) yield return item;
        }

        private static object GetProp(object obj, string name)
        {
            if (obj == null) return null;
            PropertyInfo p = obj.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (p == null) return null;
            return p.GetValue(obj, null);
        }

        private static double RequireDouble(object o, string label)
        {
            if (o == null) throw new InvalidOperationException("missing " + label);
            double v = Convert.ToDouble(o, CultureInfo.InvariantCulture);
            if (!FiniteUtil.IsFinite(v)) throw new InvalidOperationException("non-finite " + label);
            return v;
        }

        private static Exception Unwrap(Exception ex)
        {
            while (ex.InnerException != null) ex = ex.InnerException;
            return ex;
        }
    }
}
