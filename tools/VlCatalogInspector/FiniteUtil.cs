using System;

namespace VlCatalogInspector
{
    internal static class FiniteUtil
    {
        public static bool IsFinite(double v)
        {
            return !double.IsNaN(v) && !double.IsInfinity(v);
        }
    }
}
