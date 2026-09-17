using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using VirtualLabAPI.Core.Materials;

namespace VlCatalogInspector
{
    /// <summary>Live --install-dir materials export using same FormulaMap/YamlWriter semantics as dump mode.</summary>
    internal static class LiveMaterialExport
    {
        public static int Run(string installDir, string outRoot, string failListPath, out int ok, out int fail)
        {
            ok = 0;
            fail = 0;
            LicenseManager.CurrentContext = new DesignTimeLicenseContext();
            Directory.SetCurrentDirectory(installDir);

            MaterialsCatalog catalog = CatalogLoader.LoadMaterialsCatalog(installDir);
            TreeUtil.ClearMaterialsTree(outRoot);

            StandardMaterial[] entries = catalog.Entries.Cast<StandardMaterial>().ToArray();
            Dictionary<string, string> dirNames = TagLayout.UniqueDirNames(entries.Select(m => m.Name));
            var nameToDir = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var kv in dirNames) nameToDir[kv.Key] = kv.Value;

            var failLines = new List<string>();
            for (int i = 0; i < entries.Length; i++)
            {
                StandardMaterial mat = entries[i];
                string dirName = dirNames[mat.Name];
                try
                {
                    IEnumerable<string> cats = null;
                    try { cats = mat.Categories != null ? mat.Categories.Cast<string>() : null; } catch { }
                    string state = mat.StateOfMatter.ToString();
                    List<string> tags = TagLayout.BuildTags(cats, state);
                    string ymlPath = TagLayout.MaterialYmlPath(Path.Combine(outRoot, "materials"), tags, dirName);
                    string failReason;
                    if (TryWrite(mat, dirName, tags, ymlPath, nameToDir, out failReason))
                        ok++;
                    else
                    {
                        fail++;
                        failLines.Add(dirName + "\t" + mat.Name + "\t" + (failReason ?? "unsupported"));
                    }
                }
                catch (Exception ex)
                {
                    fail++;
                    failLines.Add(dirName + "\t" + mat.Name + "\t" + Unwrap(ex).Message);
                }
            }

            if (!string.IsNullOrEmpty(failListPath))
            {
                string dir = Path.GetDirectoryName(failListPath);
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
                File.WriteAllLines(failListPath, failLines.ToArray(), new UTF8Encoding(false));
            }
            Console.WriteLine("live materials: ok={0} fail={1} of {2}", ok, fail, entries.Length);
            // Known unsupported VL formula entries are counted as fail but do not abort the run.
            return ok > 0 ? 0 : 1;
        }

        private static bool TryWrite(
            StandardMaterial mat, string dirName, IList<string> tags, string ymlPath,
            IDictionary<string, string> nameToDir, out string failReason)
        {
            failReason = null;
            string dispersion = mat.DispersionFormula.ToString();
            string absorption = mat.AbsorptionFormula.ToString();
            double[] parameters = ToDoubles(mat.Parameters);
            double constAbs = mat.ConstantAbsorptionCoeff;
            bool? absN = GetPrivateBool(mat, "RefractiveIndexDefinedAsAbsolute");

            double wlMinUm, wlMaxUm;
            GetWavelengthRangeUm(mat, out wlMinUm, out wlMaxUm);

            SampledCurve sampledN = SampledCurveReader.Read(mat.SampledRefractiveIndex);
            SampledCurve sampledAlpha = SampledCurveReader.Read(mat.SampledAbsorptionCoeff);

            List<double> wlN, nVals;
            bool haveSampledN = FiniteSampledUm(sampledN, out wlN, out nVals);
            List<double> wlAlpha, alphaVals;
            bool haveAlpha = FiniteSampledUm(sampledAlpha, out wlAlpha, out alphaVals);

            var commentExtra = new List<string>();
            Dictionary<string, object> kTerm;
            if (absorption == "Sampled")
            {
                if (!haveAlpha)
                {
                    failReason = "absorption Sampled but empty SampledAbsorptionCoeff";
                    return false;
                }
                kTerm = YamlWriter.TabulatedTerm(wlAlpha, "k", OpticMath.KFromAlpha(wlAlpha, alphaVals));
                commentExtra.Add("Absorption: tabulated k from sampled alpha (α→k same points).");
            }
            else if (absorption == "Constant")
            {
                if (constAbs != 0.0)
                {
                    failReason = "constant absorption without sampled alpha grid (refusing invented λ grid)";
                    return false;
                }
                kTerm = YamlWriter.ConstantK0();
            }
            else
            {
                failReason = "unsupported AbsorptionFormula: " + absorption;
                return false;
            }

            object tRef;
            Dictionary<string, object> thermal;
            CollectThermal(mat, out tRef, out thermal);
            var catalog = new Dictionary<string, object>();
            CollectGlassCatalog(mat, catalog);

            Dictionary<string, object> data;
            object partialP = "NaN";

            if (dispersion == "Edlen_AirFormula")
            {
                commentExtra.Add("Edlen: using standard 12 formula coeffs; dump params are T/P not coeffs.");
                if (parameters.Length > 0 && FiniteUtil.IsFinite(parameters[0])) tRef = parameters[0];
                var coeffs = new List<object>();
                foreach (double c in FormulaMap.EdlenCoefficients) coeffs.Add(c);
                try
                {
                    double pp = Convert.ToDouble(mat.GetType().GetProperty("PartialPressureOfWaterVapour").GetValue(mat, null), CultureInfo.InvariantCulture);
                    if (FiniteUtil.IsFinite(pp) && pp > 0) partialP = pp;
                }
                catch { }
                object riaOut = absN.HasValue ? (object)absN.Value : true;
                data = YamlWriter.IsotropicPayload(
                    YamlWriter.AnalyticFormulaGas("formula_vl_gases_edlen", wlMinUm, wlMaxUm, coeffs),
                    kTerm, tRef, riaOut, thermal, partialP);
            }
            else if (dispersion == "Zemax_AirFormula")
            {
                commentExtra.Add("Zemax air: using standard 5 formula coeffs; dump params are T/P not coeffs.");
                if (parameters.Length > 0 && FiniteUtil.IsFinite(parameters[0])) tRef = parameters[0];
                var coeffs = new List<object>();
                foreach (double c in FormulaMap.ZemaxAirCoefficients) coeffs.Add(c);
                object riaOut = absN.HasValue ? (object)absN.Value : true;
                data = YamlWriter.IsotropicPayload(
                    YamlWriter.AnalyticFormulaGas("formula_vl_gases_zemax", wlMinUm, wlMaxUm, coeffs),
                    kTerm, tRef, riaOut, thermal, partialP);
            }
            else
            {
                string formulaId;
                int nCoeff;
                if (FormulaMap.TryGet(dispersion, out formulaId, out nCoeff))
                {
                    List<object> coeffs;
                    if (dispersion == "ConstantRefractiveIndex")
                    {
                        double nConst = double.NaN;
                        try
                        {
                            nConst = Convert.ToDouble(mat.GetType().GetProperty("ConstantRefractiveIndexValue").GetValue(mat, null), CultureInfo.InvariantCulture);
                        }
                        catch { }
                        if (FiniteUtil.IsFinite(nConst))
                            coeffs = new List<object> { nConst };
                        else if (parameters.Length > 0 && FiniteUtil.IsFinite(parameters[0]))
                            coeffs = new List<object> { parameters[0] };
                        else
                        {
                            failReason = "ConstantRefractiveIndex missing constant and Parameters[0]";
                            return false;
                        }
                    }
                    else
                        coeffs = FormulaMap.PadCoeffs(parameters, nCoeff);

                    commentExtra.Add("DispersionFormula " + dispersion + " → " + formulaId);
                    if (haveSampledN)
                        commentExtra.Add("SampledRefractiveIndex present but unused; keeping formula.");
                    object riaOut = absN.HasValue ? (object)absN.Value : "NaN";
                    data = YamlWriter.IsotropicPayload(
                        YamlWriter.AnalyticFormula(formulaId, wlMinUm, wlMaxUm, coeffs),
                        kTerm, tRef, riaOut, thermal, partialP);
                }
                else if (dispersion == "SampledDispersion")
                {
                    if (!haveSampledN)
                    {
                        failReason = "SampledDispersion but empty SampledRefractiveIndex";
                        return false;
                    }
                    commentExtra.Insert(0, "Dispersion from VirtualLab SampledRefractiveIndex table.");
                    object riaOut = absN.HasValue ? (object)absN.Value : "NaN";
                    data = YamlWriter.IsotropicPayload(
                        YamlWriter.TabulatedTerm(wlN, "n", nVals),
                        kTerm, tRef, riaOut, thermal, partialP);
                }
                else
                {
                    failReason = "unsupported DispersionFormula: " + dispersion;
                    return false;
                }
            }

            object riaVal;
            if (data.TryGetValue("refractive_index_absolute", out riaVal) && riaVal is bool && !(bool)riaVal)
            {
                string refName = null;
                try
                {
                    PropertyInfo rp = mat.GetType().GetProperty("ReferenceMaterial", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                    object rm = rp != null ? rp.GetValue(mat, null) : null;
                    if (rm != null)
                    {
                        PropertyInfo np = rm.GetType().GetProperty("Name");
                        if (np != null) refName = Convert.ToString(np.GetValue(rm, null), CultureInfo.InvariantCulture);
                    }
                }
                catch { }
                try
                {
                    string air = TagLayout.ResolveAirRef(refName, nameToDir);
                    if (air == null)
                    {
                        failReason = "relative index but no reference_material";
                        return false;
                    }
                    data["relative_air"] = new Dictionary<string, object> { { "$ref", air } };
                }
                catch (Exception ex)
                {
                    failReason = Unwrap(ex).Message;
                    return false;
                }
            }

            var comments = new StringBuilder();
            comments.Append("VirtualLab material: ").Append(mat.Name);
            foreach (string line in commentExtra)
                comments.Append('\n').Append(line);
            string references = "";
            try
            {
                string src = mat.DataSourceInformationString;
                if (!string.IsNullOrWhiteSpace(src)) references = src.Trim();
            }
            catch { }

            YamlWriter.WriteObject(ymlPath, tags, references, comments.ToString(), "", data, TagLayout.ObjectKey(dirName), catalog);
            return true;
        }

        private static void CollectThermal(StandardMaterial mat, out object tRefC, out Dictionary<string, object> thermal)
        {
            tRefC = "NaN";
            thermal = YamlWriter.ThermalNone();
            object gd = null;
            try { gd = mat.AdditionalGlassData; } catch { }
            if (gd == null) return;

            double? t = TryDouble(gd, "ReferenceTemperatureInCelsius");
            if (!t.HasValue) t = TryDouble(gd, "ReferenceTemperatureInDegrees");
            if (!t.HasValue) t = TryDouble(gd, "TemperatureReference");
            if (t.HasValue && FiniteUtil.IsFinite(t.Value)) tRefC = t.Value;

            double[] coeffs = TryDoubleArray(gd, "ThermalCoefficientsForRefractiveIndex");
            if (coeffs == null) coeffs = TryDoubleArray(gd, "ThermalDispersionCoefficients");
            if (coeffs != null && coeffs.Length >= 6)
            {
                bool any = false;
                for (int i = 0; i < 6; i++)
                    if (FiniteUtil.IsFinite(coeffs[i]) && coeffs[i] != 0.0) { any = true; break; }
                if (any)
                {
                    var list = new List<object>();
                    for (int i = 0; i < 6; i++) list.Add(coeffs[i]);
                    thermal = new Dictionary<string, object>
                    {
                        { "type", "schott_formula_a" },
                        { "coefficients", list },
                    };
                }
            }
        }

        private static void CollectGlassCatalog(StandardMaterial mat, Dictionary<string, object> catalog)
        {
            object gd = null;
            try { gd = mat.AdditionalGlassData; } catch { }
            if (gd == null) return;
            double? nd = TryDouble(gd, "RefractiveIndexN_d");
            double? vd = TryDouble(gd, "AbbeNumberNu_d");
            double? density = TryDouble(gd, "DensityInGperCCM");
            double? tce = TryDouble(gd, "ThermalExpansionCoefficient");
            if (!tce.HasValue) tce = TryDouble(gd, "TCE");
            if (nd.HasValue && nd.Value != 1.0) catalog["nd"] = nd.Value;
            if (vd.HasValue && vd.Value != 0.0) catalog["Vd"] = vd.Value;
            if (density.HasValue && density.Value > 0.0) catalog["density"] = density.Value;
            if (tce.HasValue && FiniteUtil.IsFinite(tce.Value)) catalog["TCE"] = tce.Value;
            try
            {
                PropertyInfo agf = gd.GetType().GetProperty("AGF_comment", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (agf != null)
                {
                    string s = Convert.ToString(agf.GetValue(gd, null), CultureInfo.InvariantCulture);
                    if (!string.IsNullOrWhiteSpace(s)) catalog["glass_code"] = s.Trim();
                }
            }
            catch { }
        }

        private static double? TryDouble(object obj, string prop)
        {
            try
            {
                PropertyInfo p = obj.GetType().GetProperty(prop, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (p == null) return null;
                object v = p.GetValue(obj, null);
                if (v == null) return null;
                double d = Convert.ToDouble(v, CultureInfo.InvariantCulture);
                if (!FiniteUtil.IsFinite(d)) return null;
                return d;
            }
            catch { return null; }
        }

        private static double[] TryDoubleArray(object obj, string prop)
        {
            try
            {
                PropertyInfo p = obj.GetType().GetProperty(prop, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (p == null) return null;
                object v = p.GetValue(obj, null);
                if (v == null) return null;
                var arr = v as Array;
                if (arr == null) return null;
                var a = new double[arr.Length];
                for (int i = 0; i < arr.Length; i++)
                    a[i] = Convert.ToDouble(arr.GetValue(i), CultureInfo.InvariantCulture);
                return a;
            }
            catch { return null; }
        }

        private static void GetWavelengthRangeUm(StandardMaterial mat, out double wlMinUm, out double wlMaxUm)
        {
            double? minM = GetPrivateDouble(mat, "minWavelengthIndex");
            double? maxM = GetPrivateDouble(mat, "maxWavelengthIndex");
            if (minM.HasValue && maxM.HasValue && minM.Value > 0 && maxM.Value > minM.Value)
            {
                wlMinUm = MetresToUm(minM.Value);
                wlMaxUm = MetresToUm(maxM.Value);
                return;
            }
            wlMinUm = 0.3;
            wlMaxUm = 2.5;
        }

        private static double MetresToUm(double metres)
        {
            if (metres > 0 && metres < 1e-3) return metres * 1e6;
            return metres;
        }

        private static bool FiniteSampledUm(SampledCurve c, out List<double> wlUm, out List<double> vals)
        {
            wlUm = null;
            vals = null;
            if (c == null || c.Count == 0) return false;
            wlUm = new List<double>(c.Count);
            vals = new List<double>(c.Count);
            for (int i = 0; i < c.Count; i++)
            {
                double w = c.WlM[i] * 1e6;
                double v = c.Values[i];
                if (!FiniteUtil.IsFinite(w) || !FiniteUtil.IsFinite(v)) continue;
                wlUm.Add(w);
                vals.Add(v);
            }
            return wlUm.Count > 0;
        }

        private static double[] ToDoubles(Array net)
        {
            if (net == null) return new double[0];
            var a = new double[net.Length];
            for (int i = 0; i < net.Length; i++)
                a[i] = Convert.ToDouble(net.GetValue(i), CultureInfo.InvariantCulture);
            return a;
        }

        private static double? GetPrivateDouble(object obj, string fieldName)
        {
            FieldInfo f = FindField(obj, fieldName);
            if (f == null || f.FieldType != typeof(double)) return null;
            return (double)f.GetValue(obj);
        }

        private static bool? GetPrivateBool(object obj, string fieldName)
        {
            FieldInfo f = FindField(obj, fieldName);
            if (f == null || f.FieldType != typeof(bool)) return null;
            return (bool)f.GetValue(obj);
        }

        private static FieldInfo FindField(object obj, string fieldName)
        {
            for (Type t = obj.GetType(); t != null; t = t.BaseType)
            {
                FieldInfo f = t.GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public);
                if (f != null) return f;
            }
            return null;
        }

        private static Exception Unwrap(Exception ex)
        {
            while (ex.InnerException != null) ex = ex.InnerException;
            return ex;
        }

        private sealed class DesignTimeLicenseContext : LicenseContext
        {
            public override LicenseUsageMode UsageMode
            {
                get { return LicenseUsageMode.Designtime; }
            }
        }
    }
}
