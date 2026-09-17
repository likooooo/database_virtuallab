using System;
using System.Collections.Generic;

namespace VlCatalogInspector
{
    /// <summary>VL DispersionFormula → formula_vl_* with fixed coefficient arity (pad/truncate; no rii rewrite).</summary>
    internal static class FormulaMap
    {
        public static readonly double[] EdlenCoefficients =
        {
            1e-8, 8342.13, 2406030.0, 130.0, 15997.0, 38.9,
            760.0, 1.049, 0.0157, 1e-6, 720.775, 0.003661
        };

        public static readonly double[] ZemaxAirCoefficients =
        {
            287.6155, 1.62887, 0.01360, 1e-6, 0.003661
        };

        private static readonly Dictionary<string, Tuple<string, int>> Map =
            new Dictionary<string, Tuple<string, int>>(StringComparer.Ordinal)
            {
                { "Schott", Tuple.Create("formula_vl_schott", 6) },
                { "Sellmeier1", Tuple.Create("formula_vl_sellmeier_1", 6) },
                { "Sellmeier2", Tuple.Create("formula_vl_sellmeier_2", 7) },
                { "Sellmeier3", Tuple.Create("formula_vl_sellmeier_3", 8) },
                { "Sellmeier4", Tuple.Create("formula_vl_sellmeier_4", 5) },
                { "Sellmeier5", Tuple.Create("formula_vl_sellmeier_5", 10) },
                { "Herzberger", Tuple.Create("formula_vl_herzberger", 6) },
                { "Conrady", Tuple.Create("formula_vl_conrady", 3) },
                { "Cauchy", Tuple.Create("formula_vl_cauchy", 4) },
                { "PowerSeries", Tuple.Create("formula_vl_power_series", 10) },
                { "ConstantRefractiveIndex", Tuple.Create("formula_vl_constant", 1) },
                { "HandbookOptics1", Tuple.Create("formula_vl_handbook_optics_1", 6) },
                { "HandbookOptics2", Tuple.Create("formula_vl_handbook_optics_2", 4) },
            };

        public static bool TryGet(string dispersion, out string formulaId, out int coeffCount)
        {
            formulaId = null;
            coeffCount = 0;
            if (string.IsNullOrEmpty(dispersion)) return false;
            Tuple<string, int> t;
            if (!Map.TryGetValue(dispersion.Trim(), out t)) return false;
            formulaId = t.Item1;
            coeffCount = t.Item2;
            return true;
        }

        public static List<object> PadCoeffs(IList<double> parameters, int n)
        {
            var outList = new List<object>(n);
            int take = parameters == null ? 0 : Math.Min(parameters.Count, n);
            for (int i = 0; i < take; i++) outList.Add(parameters[i]);
            while (outList.Count < n) outList.Add(0.0);
            return outList;
        }
    }
}
