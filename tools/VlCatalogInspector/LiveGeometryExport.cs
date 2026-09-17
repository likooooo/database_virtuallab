using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;

namespace VlCatalogInspector
{
    /// <summary>Live Interfaces + Boundary catalogs → lossy core geometries (no datas dump).</summary>
    internal static class LiveGeometryExport
    {
        public static void Run(string installDir, string outRoot, string notesDir, out int ok, out int skip)
        {
            ok = 0;
            skip = 0;
            TreeUtil.ClearYmlTree(Path.Combine(outRoot, "geometries"));
            var skipLines = new List<string>();

            CatalogSlice interfaces = CatalogLoader.LoadInterfaces(installDir);
            var used = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < interfaces.Entries.Length; i++)
            {
                object entry = interfaces.Entries[i];
                string rawName = (i < interfaces.Names.Length) ? interfaces.Names[i] : "interface_" + i;
                string stem = UniqueStem(rawName, used);
                string reason;
                if (TryExportInterface(entry, rawName, stem, outRoot, out reason)) ok++;
                else
                {
                    skip++;
                    skipLines.Add("interface\t" + stem + "\t" + reason);
                }
            }

            CatalogSlice boundaries = CatalogLoader.LoadBoundaries(installDir);
            for (int i = 0; i < boundaries.Entries.Length; i++)
            {
                object entry = boundaries.Entries[i];
                string rawName = (i < boundaries.Names.Length) ? boundaries.Names[i] : "boundary_" + i;
                string stem = UniqueStem(rawName, used);
                string reason;
                if (TryExportBoundary(entry, rawName, stem, outRoot, out reason)) ok++;
                else
                {
                    skip++;
                    skipLines.Add("boundary\t" + stem + "\t" + reason);
                }
            }

            if (!string.IsNullOrEmpty(notesDir))
            {
                Directory.CreateDirectory(notesDir);
                File.WriteAllLines(Path.Combine(notesDir, "geo_skip.txt"), skipLines.ToArray(), new UTF8Encoding(false));
            }
            Console.WriteLine("live geometries: ok={0} skip={1} (see notes/geo_skip.txt)", ok, skip);
        }

        private static string UniqueStem(string rawName, HashSet<string> used)
        {
            string stem = TagLayout.SafeDirName(rawName);
            string candidate = stem;
            int n = 2;
            while (!used.Add(candidate))
            {
                candidate = stem + "_" + n.ToString(CultureInfo.InvariantCulture);
                n++;
            }
            return candidate;
        }

        private static bool TryExportInterface(object entry, string rawName, string stem, string outRoot, out string reason)
        {
            reason = null;
            try
            {
                string shortType = entry != null ? entry.GetType().Name : "";
                if (shortType.StartsWith("Programmable", StringComparison.Ordinal) ||
                    shortType.StartsWith("Combined", StringComparison.Ordinal))
                {
                    reason = "skip " + shortType;
                    return false;
                }
                if (shortType == "AsphericalInterface")
                    return WriteAsphereSphere(entry, rawName, stem, outRoot, out reason);
                if (shortType == "BinaryGratingInterface1D" ||
                    shortType == "BlazedGratingInterface1D" ||
                    shortType == "SineModulatedGratingInterface1D" ||
                    shortType == "TriangularGratingInterface1D")
                    return WriteGratingRect(entry, rawName, stem, outRoot, shortType, out reason);
                reason = "unsupported type " + shortType;
                return false;
            }
            catch (Exception ex)
            {
                reason = Unwrap(ex).Message;
                return false;
            }
        }

        private static bool TryExportBoundary(object entry, string rawName, string stem, string outRoot, out string reason)
        {
            reason = null;
            try
            {
                string shortType = entry != null ? entry.GetType().Name : "";
                if (shortType.StartsWith("Programmable", StringComparison.Ordinal))
                {
                    reason = "skip " + shortType;
                    return false;
                }
                if (shortType != "ApertureBoundaryResponse" && shortType != "StopBoundaryOperator")
                {
                    reason = "unsupported type " + shortType;
                    return false;
                }
                object op = GetProp(entry, "Operator") ?? entry;
                string shape = Convert.ToString(GetProp(op, "ApertureShape"), CultureInfo.InvariantCulture) ?? "";
                double hx, hy;
                if (!TryApertureHalfwidthUm(op, out hx, out hy))
                {
                    reason = "ApertureSize has no usable X/Y";
                    return false;
                }
                string comments = "VirtualLab boundary: " + rawName
                    + "\nLossy: " + shortType + " ApertureShape=" + shape + " → core 2d shape.";
                List<string> tags = TagLayout.BuildTags(new[] { "2d" }, "Solid", keepUnmappedCategory: true);
                string key = TagLayout.ObjectKey(stem);
                Dictionary<string, object> payload;
                if (string.Equals(shape, "Rectangular", StringComparison.OrdinalIgnoreCase))
                    payload = AsCollection(RectPayload(hx, hy));
                else if (string.Equals(shape, "Elliptic", StringComparison.OrdinalIgnoreCase) ||
                         string.Equals(shape, "Elliptical", StringComparison.OrdinalIgnoreCase))
                    payload = AsCollection(AlmostEqual(hx, hy) ? CirclePayload(hx) : EllipsePayload(hx, hy));
                else
                {
                    reason = "unsupported ApertureShape " + shape;
                    return false;
                }
                string outPath = Path.Combine(outRoot, "geometries", "2d", TagLayout.KeySafeStem(stem) + ".yml");
                YamlWriter.WriteObject(outPath, tags, "", comments, "", payload, key, null);
                return true;
            }
            catch (Exception ex)
            {
                reason = Unwrap(ex).Message;
                return false;
            }
        }

        private static bool WriteAsphereSphere(object entry, string rawName, string stem, string outRoot, out string reason)
        {
            reason = null;
            double rM;
            if (!TryDouble(GetProp(entry, "Radius"), out rM) || !FiniteUtil.IsFinite(rM) || rM == 0.0)
            {
                reason = "no usable Radius";
                return false;
            }
            double radiusUm = Math.Abs(rM) * 1e6;
            string comments = "VirtualLab interface: " + rawName
                + "\nLossy: AsphericalInterface → sphere using Radius only; asphere/conic terms discarded."
                + "\nConicalConstant=" + Convert.ToString(GetProp(entry, "ConicalConstant"), CultureInfo.InvariantCulture);
            List<string> tags = TagLayout.BuildTags(new[] { "3d" }, "Solid", keepUnmappedCategory: true);
            string key = TagLayout.ObjectKey(stem);
            var leaf = new Dictionary<string, object>
            {
                { "type", "sphere" },
                { "radius", radiusUm },
                { "center", new List<object> { 0.0, 0.0, 0.0 } },
                { "euler_angles", new List<object> { 0.0, 0.0, 0.0 } },
                { "material", new Dictionary<string, object> { { "$ref", "vl/Air" } } },
            };
            string outPath = Path.Combine(outRoot, "geometries", "3d", TagLayout.KeySafeStem(stem) + ".yml");
            YamlWriter.WriteObject(outPath, tags, "", comments, "", AsCollection(leaf), key, null);
            return true;
        }

        private static bool WriteGratingRect(
            object entry, string rawName, string stem, string outRoot, string shortType, out string reason)
        {
            reason = null;
            double sx = double.NaN, sy = double.NaN;
            if (!TryDouble(GetProp(entry, "DefinitionArea_Size_X"), out sx) ||
                !TryDouble(GetProp(entry, "DefinitionArea_Size_Y"), out sy))
            {
                object defArea = GetProp(entry, "DefinitionArea");
                if (defArea != null)
                {
                    TryDouble(GetProp(defArea, "Size_X") ?? GetProp(defArea, "SizeX") ?? GetNestedSize(defArea, 0), out sx);
                    TryDouble(GetProp(defArea, "Size_Y") ?? GetProp(defArea, "SizeY") ?? GetNestedSize(defArea, 1), out sy);
                }
                if (!FiniteUtil.IsFinite(sx) || !FiniteUtil.IsFinite(sy) || sx <= 0 || sy <= 0)
                {
                    double p;
                    if (TryDouble(GetProp(entry, "Period1D"), out p) && FiniteUtil.IsFinite(p) && p > 0)
                    {
                        sx = p;
                        sy = p;
                    }
                    else
                    {
                        reason = "no DefinitionArea size or Period1D";
                        return false;
                    }
                }
            }
            if (!FiniteUtil.IsFinite(sx) || !FiniteUtil.IsFinite(sy) || sx <= 0 || sy <= 0)
            {
                reason = "non-finite or non-positive DefinitionArea size";
                return false;
            }
            double hx = sx * 1e6 / 2.0;
            double hy = sy * 1e6 / 2.0;
            string comments = "VirtualLab interface: " + rawName
                + "\nLossy: " + shortType + " → rect from DefinitionArea size (period profile discarded)."
                + "\nPeriod1D_m=" + Convert.ToString(GetProp(entry, "Period1D"), CultureInfo.InvariantCulture);
            List<string> tags = TagLayout.BuildTags(new[] { "2d" }, "Solid", keepUnmappedCategory: true);
            string key = TagLayout.ObjectKey(stem);
            string outPath = Path.Combine(outRoot, "geometries", "2d", TagLayout.KeySafeStem(stem) + ".yml");
            YamlWriter.WriteObject(outPath, tags, "", comments, "", AsCollection(RectPayload(hx, hy)), key, null);
            return true;
        }

        /// <summary>GUI MVP edits sub-shapes only when root is geometry_collection; leaf stays inline in shapes[].</summary>
        private static Dictionary<string, object> AsCollection(Dictionary<string, object> leaf)
        {
            return new Dictionary<string, object>
            {
                { "type", "geometry_collection" },
                { "shapes", new List<object> { leaf } },
            };
        }

        private static object GetNestedSize(object defArea, int index)
        {
            object size = GetProp(defArea, "Size");
            if (size == null) return null;
            if (size is Array)
            {
                var arr = (Array)size;
                if (index < arr.Length) return arr.GetValue(index);
            }
            try
            {
                PropertyInfo item = size.GetType().GetProperty("Item");
                if (item != null) return item.GetValue(size, new object[] { index });
            }
            catch { }
            return null;
        }

        private static Dictionary<string, object> RectPayload(double halfW, double halfH)
        {
            return new Dictionary<string, object>
            {
                { "type", "rect" },
                { "halfwidth", new List<object> { halfW, halfH } },
                { "center", new List<object> { 0.0, 0.0 } },
                { "angle", 0.0 },
                { "material", new Dictionary<string, object> { { "$ref", "vl/Air" } } },
            };
        }

        private static Dictionary<string, object> CirclePayload(double radius)
        {
            return new Dictionary<string, object>
            {
                { "type", "circle" },
                { "radius", radius },
                { "center", new List<object> { 0.0, 0.0 } },
                { "angle", 0.0 },
                { "material", new Dictionary<string, object> { { "$ref", "vl/Air" } } },
            };
        }

        private static Dictionary<string, object> EllipsePayload(double a, double b)
        {
            return new Dictionary<string, object>
            {
                { "type", "ellipse" },
                { "halfwidth", new List<object> { a, b } },
                { "center", new List<object> { 0.0, 0.0 } },
                { "angle", 0.0 },
                { "material", new Dictionary<string, object> { { "$ref", "vl/Air" } } },
            };
        }

        private static bool TryApertureHalfwidthUm(object op, out double hx, out double hy)
        {
            hx = hy = 0;
            double x, y;
            if (TryDouble(GetProp(op, "ApertureSize_X"), out x) && TryDouble(GetProp(op, "ApertureSize_Y"), out y)
                && FiniteUtil.IsFinite(x) && FiniteUtil.IsFinite(y) && x > 0 && y > 0)
            {
                hx = x * 1e6 / 2.0;
                hy = y * 1e6 / 2.0;
                return true;
            }
            object size = GetProp(op, "ApertureSize");
            if (size != null)
            {
                if (TryDouble(GetProp(size, "X"), out x) && TryDouble(GetProp(size, "Y"), out y)
                    && FiniteUtil.IsFinite(x) && FiniteUtil.IsFinite(y) && x > 0 && y > 0)
                {
                    hx = x * 1e6 / 2.0;
                    hy = y * 1e6 / 2.0;
                    return true;
                }
                if (size is Array)
                {
                    var arr = (Array)size;
                    if (arr.Length >= 2
                        && TryDouble(arr.GetValue(0), out x) && TryDouble(arr.GetValue(1), out y)
                        && FiniteUtil.IsFinite(x) && FiniteUtil.IsFinite(y) && x > 0 && y > 0)
                    {
                        hx = x * 1e6 / 2.0;
                        hy = y * 1e6 / 2.0;
                        return true;
                    }
                }
            }
            return false;
        }

        private static object GetProp(object obj, string name)
        {
            if (obj == null) return null;
            PropertyInfo p = obj.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (p == null) return null;
            try { return p.GetValue(obj, null); }
            catch { return null; }
        }

        private static bool TryDouble(object o, out double v)
        {
            v = double.NaN;
            if (o == null) return false;
            try
            {
                v = Convert.ToDouble(o, CultureInfo.InvariantCulture);
                return true;
            }
            catch { return false; }
        }

        private static bool AlmostEqual(double a, double b)
        {
            double scale = Math.Max(Math.Abs(a), Math.Abs(b));
            return Math.Abs(a - b) <= 1e-12 * Math.Max(1.0, scale);
        }

        private static Exception Unwrap(Exception ex)
        {
            while (ex.InnerException != null) ex = ex.InnerException;
            return ex;
        }
    }
}
