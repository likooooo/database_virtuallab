using System;
using System.Collections.Generic;

namespace VlCatalogInspector
{
    internal static class OpticMath
    {
        public static List<double> KFromAlpha(IList<double> wlUm, IList<double> alpha)
        {
            if (wlUm.Count != alpha.Count)
                throw new ArgumentException("alpha→k requires same-length wl and alpha");
            var k = new List<double>(wlUm.Count);
            for (int i = 0; i < wlUm.Count; i++)
                k.Add(alpha[i] * (wlUm[i] * 1e-6) / (4.0 * Math.PI));
            return k;
        }
    }
}
