using System;
using System.Globalization;
using System.Reflection;

namespace VlCatalogInspector
{
    internal sealed class SampledCurve
    {
        public double[] WlM;
        public double[] Values;
        public int Count { get { return WlM != null ? WlM.Length : 0; } }
    }

    /// <summary>Read VirtualLab 1D sampled field (wavelength metres).</summary>
    internal static class SampledCurveReader
    {
        public static SampledCurve Read(object da)
        {
            if (da == null) return null;
            try
            {
                int n = Convert.ToInt32(da.GetType().GetProperty("NoOfDataPoints").GetValue(da, null), CultureInfo.InvariantCulture);
                if (n <= 0) return null;
                var wl = new double[n];
                bool equi = false;
                try { equi = Convert.ToBoolean(da.GetType().GetProperty("IsEquidistant").GetValue(da, null)); } catch { }

                if (equi)
                {
                    double start = Convert.ToDouble(da.GetType().GetProperty("CoordinateOfFirstDataPoint").GetValue(da, null), CultureInfo.InvariantCulture);
                    double step = Convert.ToDouble(da.GetType().GetProperty("SamplingDistance").GetValue(da, null), CultureInfo.InvariantCulture);
                    for (int i = 0; i < n; i++) wl[i] = start + i * step;
                }
                else
                {
                    object nc = da.GetType().GetProperty("NonequidistantCoordinates").GetValue(da, null);
                    for (int i = 0; i < n; i++)
                        wl[i] = Convert.ToDouble(IndexedGet(nc, i), CultureInfo.InvariantCulture);
                }

                object data = da.GetType().GetProperty("Data").GetValue(da, null);
                object field = IndexedGet(data, 0);
                var vals = new double[n];
                bool realField = field != null && field.GetType().Name == "CFieldDerivative1DReal";
                FieldInfo reField = null;
                for (int i = 0; i < n; i++)
                {
                    object raw = IndexedGet(field, i);
                    if (realField)
                        vals[i] = Convert.ToDouble(raw, CultureInfo.InvariantCulture);
                    else
                    {
                        if (reField == null && raw != null)
                            reField = raw.GetType().GetField("Re", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                        vals[i] = reField != null
                            ? Convert.ToDouble(reField.GetValue(raw), CultureInfo.InvariantCulture)
                            : Convert.ToDouble(raw, CultureInfo.InvariantCulture);
                    }
                }
                return new SampledCurve { WlM = wl, Values = vals };
            }
            catch
            {
                return null;
            }
        }

        private static object IndexedGet(object target, int index)
        {
            if (target == null) return null;
            if (target is Array) return ((Array)target).GetValue(index);

            foreach (MethodInfo m in target.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public))
            {
                if (m.Name != "get_Item" && m.Name != "GetValue") continue;
                ParameterInfo[] ps = m.GetParameters();
                if (ps.Length != 1) continue;
                try
                {
                    object arg = Convert.ChangeType(index, ps[0].ParameterType, CultureInfo.InvariantCulture);
                    return m.Invoke(target, new[] { arg });
                }
                catch { }
            }

            PropertyInfo item = target.GetType().GetProperty("Item");
            if (item != null)
            {
                try { return item.GetValue(target, new object[] { index }); } catch { }
                try { return item.GetValue(target, new object[] { (long)index }); } catch { }
            }
            return null;
        }
    }
}
