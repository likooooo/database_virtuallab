using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace VlCatalogInspector
{
    /// <summary>
    /// TAGS layout aligned with harness docs/tag_taxonomy.md and framework/material_tags.py.
    /// </summary>
    internal static class TagLayout
    {
        private static readonly HashSet<string> SpectralRaw = new HashSet<string>(StringComparer.Ordinal)
        {
            "Infrared", "X-ray"
        };

        private static readonly HashSet<string> VendorRaw = new HashSet<string>(StringComparer.Ordinal)
        {
            "Schott_2015", "Ohara_2016", "Hikari_2016", "CDGM_2016", "Hoya_2015",
            "Sumita_2016", "LZOS_2014", "Corning", "Heraeus", "Dow_2001"
        };

        private static readonly Dictionary<string, string> PlusRename = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "Metals+Compounds", "MetalsAndCompounds" },
            { "Carbon+Compounds", "CarbonAndCompounds" },
            { "Silicon+Compounds_Non-Glass", "SiliconAndCompounds_Non-Glass" },
        };

        private static readonly Dictionary<string, string> CategoryClosed = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { "MetalsAndCompounds", "metal" },
            { "Metals", "metal" },
            { "SiliconAndCompounds_Non-Glass", "semiconductor" },
            { "semiconductoralloys", "semiconductor" },
            { "Oxides", "dielectric" },
            { "Coating_Materials", "dielectric" },
            { "dopedcrystals", "crystal" },
            { "mixedcrystals", "crystal" },
            { "crystallineminerals", "crystal" },
            { "Polymers", "organic" },
            { "Small-molecules", "organic" },
            { "Blends", "organic" },
            { "resists", "organic" },
            { "commercialpolymers", "organic" },
            { "mixedorganic", "organic" },
            { "Liquids", "liquid" },
            { "liquidcrystals", "liquid" },
            { "buffersolutions", "liquid" },
            { "Gases", "gas" },
            { "mixedgases", "gas" },
            { "Perovskites", "perovskite" },
            { "alloys", "alloy" },
            { "intermetallics", "alloy" },
            { "finite_size", "composite" },
            { "mixedorganic-inorganic", "composite" },
            { "Glasses", "glass" },
            { "optical", "glass" },
            { "Miscellaneous", "misc" },
            { "Generic", "misc" },
            { "formula", "misc" },
            { "CarbonAndCompounds", "misc" },
            { "glass", "glass" },
            { "metal", "metal" },
            { "semiconductor", "semiconductor" },
            { "dielectric", "dielectric" },
            { "crystal", "crystal" },
            { "organic", "organic" },
            { "liquid", "liquid" },
            { "gas", "gas" },
            { "perovskite", "perovskite" },
            { "misc", "misc" },
            { "alloy", "alloy" },
            { "composite", "composite" },
        };

        private static readonly HashSet<string> OwnershipTags = new HashSet<string>(StringComparer.Ordinal)
        {
            "Predefined", "UserDefined"
        };

        private static readonly HashSet<string> SourceTags = new HashSet<string>(StringComparer.Ordinal)
        {
            "vl", "fs", "gf", "og", "pd", "of"
        };

        private static readonly Regex TagBad = new Regex(@"[^A-Za-z0-9_./+\-:]", RegexOptions.Compiled);
        private static readonly Regex VendorYear = new Regex(@"_(\d{4})$", RegexOptions.Compiled);

        public static string SanitizeTag(string tag)
        {
            if (tag == null) throw new ArgumentException("tag is null");
            string s = Regex.Replace(tag.Trim(), @"\s+", "");
            s = TagBad.Replace(s, "_");
            while (s.Contains("__")) s = s.Replace("__", "_");
            s = s.Trim('_');
            if (string.IsNullOrEmpty(s))
                throw new ArgumentException("tag empty after sanitize: " + tag);
            return s;
        }

        public static string VendorStem(string raw)
        {
            string s = SanitizeTag(raw);
            s = VendorYear.Replace(s, "");
            return s.ToLowerInvariant();
        }

        public static string SafeDirName(string name)
        {
            var sb = new StringBuilder((name ?? "").Length);
            foreach (char ch in name ?? "")
                sb.Append(Regex.IsMatch(ch.ToString(), @"[a-zA-Z0-9_]") ? ch : '_');
            string result = sb.ToString();
            while (result.Contains("__")) result = result.Replace("__", "_");
            result = result.Trim('_');
            if (string.IsNullOrEmpty(result)) result = "object";
            if (char.IsDigit(result[0])) result = "m_" + result;
            if (result.Length > 180) result = result.Substring(0, 180).TrimEnd('_');
            return result;
        }

        public static Dictionary<string, string> UniqueDirNames(IEnumerable<string> names)
        {
            var used = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var map = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (string name in names)
            {
                string baseName = SafeDirName(name);
                string candidate = baseName;
                int i = 2;
                while (!used.Add(candidate))
                {
                    string suffix = "_" + i.ToString(CultureInfo.InvariantCulture);
                    int maxLen = 180 - suffix.Length;
                    candidate = (baseName.Length > maxLen ? baseName.Substring(0, maxLen).TrimEnd('_') : baseName) + suffix;
                    i++;
                }
                map[name] = candidate;
            }
            return map;
        }

        public static List<string> BuildTags(IEnumerable<string> categories, string stateOfMatter)
        {
            return BuildTags(categories, stateOfMatter, keepUnmappedCategory: false);
        }

        public static List<string> BuildTags(IEnumerable<string> categories, string stateOfMatter, bool keepUnmappedCategory)
        {
            var tags = new List<string>();
            var seen = new HashSet<string>(StringComparer.Ordinal);
            tags.Add("vl");
            seen.Add("vl");
            bool hasVendor = false;
            if (categories != null)
            {
                foreach (string c in categories)
                {
                    if (string.IsNullOrWhiteSpace(c)) continue;
                    string raw = SanitizeTag(c);
                    if (raw == "virtuallab" || raw == "vl") continue;
                    string t;
                    if (SpectralRaw.Contains(raw))
                        t = "spectrum:" + raw;
                    else if (VendorRaw.Contains(raw))
                    {
                        t = "vendor:" + VendorStem(raw);
                        hasVendor = true;
                    }
                    else
                    {
                        string renamed;
                        if (!PlusRename.TryGetValue(raw, out renamed))
                            renamed = raw;
                        string closed;
                        if (CategoryClosed.TryGetValue(renamed, out closed))
                            t = "category:" + closed;
                        else if (keepUnmappedCategory)
                            t = "category:" + renamed;
                        else
                            continue;
                    }
                    if (!seen.Add(t)) continue;
                    tags.Add(t);
                }
            }
            if (hasVendor && seen.Add("category:glass"))
                tags.Add("category:glass");
            string st = StateTag(stateOfMatter);
            if (!seen.Add(st))
                throw new InvalidOperationException("duplicate state tag " + st);
            tags.Add(st);
            return tags;
        }

        public static string PrimaryTag(IList<string> tags)
        {
            var vendors = new List<string>();
            var categories = new List<string>();
            var other = new List<string>();
            foreach (string t in tags)
            {
                if (t.StartsWith("state:", StringComparison.Ordinal)) continue;
                if (t.StartsWith("spectrum:", StringComparison.Ordinal)) continue;
                if (t.StartsWith("shelf:", StringComparison.Ordinal)) continue;
                if (t.StartsWith("substance:", StringComparison.Ordinal)) continue;
                if (t.StartsWith("formula:", StringComparison.Ordinal)) continue;
                if (t.StartsWith("catalog:", StringComparison.Ordinal)) continue;
                if (OwnershipTags.Contains(t)) continue;
                if (SourceTags.Contains(t)) continue;
                if (t.StartsWith("rii_", StringComparison.Ordinal)) continue;
                if (t.StartsWith("vendor:", StringComparison.Ordinal))
                    vendors.Add(t.Substring("vendor:".Length));
                else if (t.StartsWith("category:", StringComparison.Ordinal))
                    categories.Add(t.Substring("category:".Length));
                else
                    other.Add(t);
            }
            List<string> pool = vendors.Count > 0 ? vendors : (categories.Count > 0 ? categories : other);
            if (pool.Count == 0) return "Miscellaneous";
            pool.Sort(StringComparer.Ordinal);
            return SafeDirName(pool[0]);
        }

        public static string KeySafeStem(string dirName)
        {
            string s = (dirName ?? "")
                .Replace("µm", "um").Replace("μm", "um")
                .Replace("µ", "um").Replace("μ", "um");
            s = Regex.Replace(s, @"\s+", "");
            var sb = new StringBuilder(s.Length);
            foreach (char ch in s)
            {
                if ((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9')
                    || ch == '_' || ch == '-' || ch == '.' || ch == '+' || ch == ':')
                    sb.Append(ch);
                else
                    sb.Append('_');
            }
            string result = sb.ToString();
            while (result.Contains("__")) result = result.Replace("__", "_");
            result = result.Trim('_');
            if (string.IsNullOrEmpty(result)) result = "object";
            return result;
        }

        public static string ObjectKey(string dirName)
        {
            return "vl/" + KeySafeStem(dirName);
        }

        public static string MaterialYmlPath(string materialsRoot, IList<string> tags, string dirName)
        {
            return System.IO.Path.Combine(materialsRoot, PrimaryTag(tags), KeySafeStem(dirName) + ".yml");
        }

        public static string ResolveAirRef(string referenceMaterial, IDictionary<string, string> nameToDir)
        {
            if (string.IsNullOrWhiteSpace(referenceMaterial)) return null;
            string dir;
            if (nameToDir.TryGetValue(referenceMaterial, out dir))
                return ObjectKey(dir);
            string aliasTarget = null;
            if (referenceMaterial == "Standard Air")
                aliasTarget = "Air";
            else if (referenceMaterial == "Air (Zemax)" || referenceMaterial == "Air (ZEMAX)")
                aliasTarget = "Air (Zemax OS)";
            if (aliasTarget != null && nameToDir.TryGetValue(aliasTarget, out dir))
                return ObjectKey(dir);
            throw new InvalidOperationException("unresolved reference_material " + referenceMaterial);
        }

        private static string StateTag(string stateOfMatter)
        {
            string s = (stateOfMatter ?? "").Trim();
            if (string.Equals(s, "Solid", StringComparison.OrdinalIgnoreCase)) return "state:Solid";
            if (string.Equals(s, "Liquid", StringComparison.OrdinalIgnoreCase)) return "state:Liquid";
            if (string.Equals(s, "GasOrVacuum", StringComparison.OrdinalIgnoreCase)) return "state:GasOrVacuum";
            if (string.Equals(s, "Gas", StringComparison.OrdinalIgnoreCase)) return "state:GasOrVacuum";
            if (string.Equals(s, "Vacuum", StringComparison.OrdinalIgnoreCase)) return "state:GasOrVacuum";
            throw new InvalidOperationException("unsupported StateOfMatter: " + stateOfMatter);
        }
    }
}
