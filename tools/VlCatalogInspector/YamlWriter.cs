using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace VlCatalogInspector
{
    /// <summary>Hand-written YAML matching framework.emit_material_yaml (TAGS; name inside DATA; quoted sentinels).</summary>
    internal static class YamlWriter
    {
        public static void WriteObject(
            string path,
            IList<string> tags,
            string references,
            string comments,
            string conditions,
            Dictionary<string, object> data,
            string name,
            Dictionary<string, object> catalog)
        {
            if (tags == null || tags.Count == 0)
                throw new ArgumentException("TAGS must be non-empty");
            if (data == null || !data.ContainsKey("type"))
                throw new ArgumentException("DATA.type required");
            if (string.IsNullOrEmpty(name))
                throw new ArgumentException("name required");

            var payload = new Dictionary<string, object>(data);
            if (catalog != null)
            {
                foreach (string key in new[] { "nd", "Vd", "density", "TCE", "glass_code" })
                {
                    object v;
                    if (catalog.TryGetValue(key, out v) && v != null)
                        payload[key] = v;
                }
            }
            payload["name"] = name;

            var sb = new StringBuilder();
            sb.AppendLine("TAGS:");
            foreach (string t in tags)
                sb.Append("  - ").AppendLine(YamlScalar(t));
            AppendBlock(sb, "REFERENCES", references ?? "");
            AppendBlock(sb, "COMMENTS", comments ?? "");
            AppendBlock(sb, "CONDITIONS", conditions ?? "");
            sb.AppendLine("DATA:");
            WriteMapping(sb, payload, 1);

            string dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);
            File.WriteAllText(path, sb.ToString(), new UTF8Encoding(false));
        }

        public static Dictionary<string, object> AnalyticFormula(string formula, object wlMin, object wlMax, IList<object> coefficients)
        {
            return new Dictionary<string, object>
            {
                { "type", "analytic_formula" },
                { "formula", formula },
                { "wl_min", wlMin },
                { "wl_max", wlMax },
                { "coefficients", new List<object>(coefficients) },
            };
        }

        public static Dictionary<string, object> AnalyticFormulaGas(string formula, object wlMin, object wlMax, IList<object> coefficients)
        {
            return new Dictionary<string, object>
            {
                { "type", "analytic_formula_gas" },
                { "formula", formula },
                { "wl_min", wlMin },
                { "wl_max", wlMax },
                { "coefficients", new List<object>(coefficients) },
            };
        }

        public static Dictionary<string, object> ConstantTerm(double value)
        {
            return AnalyticFormula("formula_vl_constant", "-Infinity", "Infinity", new List<object> { value });
        }

        public static Dictionary<string, object> ConstantK0()
        {
            return ConstantTerm(0.0);
        }

        public static Dictionary<string, object> TabulatedTerm(IList<double> x, string channel, IList<double> values)
        {
            if (channel != "n" && channel != "k")
                throw new ArgumentException("channel must be n or k");
            if (x == null || values == null || x.Count == 0 || x.Count != values.Count)
                throw new ArgumentException("tabulated_curve length mismatch / empty");
            var channels = new Dictionary<string, object> { { channel, ToObjList(values) } };
            var curve = new Dictionary<string, object>
            {
                { "type", "tabulated_curve" },
                { "x", ToObjList(x) },
                { "x_unit", "um" },
                { "interpolator", "linear" },
                { "endpoint_low", "clamp" },
                { "endpoint_high", "clamp" },
                { "interpolator_params", new Dictionary<string, object>() },
                { "channels", channels },
            };
            return new Dictionary<string, object>
            {
                { "type", "tabulated" },
                { "curve", curve },
            };
        }

        public static Dictionary<string, object> ThermalNone()
        {
            return new Dictionary<string, object>
            {
                { "type", "schott_formula_a" },
                { "coefficients", new List<object> { "NaN", "NaN", "NaN", "NaN", "NaN", "NaN" } },
            };
        }

        public static Dictionary<string, object> IsotropicPayload(
            Dictionary<string, object> n,
            Dictionary<string, object> k,
            object tRefC,
            object refractiveIndexAbsolute,
            Dictionary<string, object> thermal,
            object partialPressureWaterPa)
        {
            return new Dictionary<string, object>
            {
                { "type", "isotropic_dispersion" },
                { "T_ref_C", tRefC },
                { "refractive_index_absolute", refractiveIndexAbsolute },
                { "n", n },
                { "k", k },
                { "thermal_dispersion", thermal ?? ThermalNone() },
                { "partial_pressure_water_Pa", partialPressureWaterPa ?? "NaN" },
            };
        }

        private static List<object> ToObjList(IList<double> xs)
        {
            var list = new List<object>(xs.Count);
            foreach (double x in xs) list.Add(x);
            return list;
        }

        private static void AppendBlock(StringBuilder sb, string key, string text)
        {
            sb.Append(key).AppendLine(": |");
            if (string.IsNullOrEmpty(text)) return;
            foreach (string line in text.Replace("\r\n", "\n").Split('\n'))
                sb.Append("  ").AppendLine(line);
        }

        private static void WriteMapping(StringBuilder sb, Dictionary<string, object> map, int indent)
        {
            string pad = new string(' ', indent * 2);
            foreach (KeyValuePair<string, object> kv in map)
            {
                sb.Append(pad).Append(kv.Key).Append(": ");
                WriteValue(sb, kv.Value, indent);
            }
        }

        private static void WriteValue(StringBuilder sb, object value, int indent)
        {
            if (value == null)
            {
                sb.AppendLine("null");
                return;
            }
            if (value is bool)
            {
                sb.AppendLine((bool)value ? "true" : "false");
                return;
            }
            if (value is int)
            {
                sb.AppendLine(((int)value).ToString(CultureInfo.InvariantCulture));
                return;
            }
            if (value is long)
            {
                sb.AppendLine(((long)value).ToString(CultureInfo.InvariantCulture));
                return;
            }
            if (value is float)
            {
                sb.AppendLine(Fmt((double)(float)value));
                return;
            }
            if (value is double)
            {
                sb.AppendLine(Fmt((double)value));
                return;
            }
            if (value is decimal)
            {
                sb.AppendLine(Fmt((double)(decimal)value));
                return;
            }
            if (value is string)
            {
                string s = (string)value;
                if (s == "NaN" || s == "Infinity" || s == "-Infinity")
                {
                    sb.Append('"').Append(s).Append('"').AppendLine();
                    return;
                }
                sb.AppendLine(YamlScalar(s));
                return;
            }
            var list = value as List<object>;
            if (list != null)
            {
                if (list.Count == 0)
                {
                    sb.AppendLine("[]");
                    return;
                }
                sb.AppendLine();
                string pad = new string(' ', (indent + 1) * 2);
                foreach (object item in list)
                {
                    if (item is Dictionary<string, object>)
                    {
                        sb.Append(pad).Append("- ");
                        var nested = (Dictionary<string, object>)item;
                        bool first = true;
                        foreach (KeyValuePair<string, object> nk in nested)
                        {
                            if (first)
                            {
                                sb.Append(nk.Key).Append(": ");
                                WriteValue(sb, nk.Value, indent + 2);
                                first = false;
                            }
                            else
                            {
                                sb.Append(new string(' ', (indent + 2) * 2)).Append(nk.Key).Append(": ");
                                WriteValue(sb, nk.Value, indent + 2);
                            }
                        }
                    }
                    else if (item is string && ((string)item == "NaN" || (string)item == "Infinity" || (string)item == "-Infinity"))
                        sb.Append(pad).Append("- \"").Append((string)item).Append('"').AppendLine();
                    else if (item is double)
                        sb.Append(pad).Append("- ").AppendLine(Fmt((double)item));
                    else if (item is float)
                        sb.Append(pad).Append("- ").AppendLine(Fmt((double)(float)item));
                    else if (item is decimal)
                        sb.Append(pad).Append("- ").AppendLine(Fmt((double)(decimal)item));
                    else
                        sb.Append(pad).Append("- ").AppendLine(Convert.ToString(item, CultureInfo.InvariantCulture));
                }
                return;
            }
            var dict = value as Dictionary<string, object>;
            if (dict != null)
            {
                if (dict.Count == 0)
                {
                    sb.AppendLine("{}");
                    return;
                }
                sb.AppendLine();
                WriteMapping(sb, dict, indent + 1);
                return;
            }
            sb.AppendLine(Convert.ToString(value, CultureInfo.InvariantCulture));
        }

        private static string Fmt(double v)
        {
            if (double.IsNaN(v)) return "\"NaN\"";
            if (double.IsPositiveInfinity(v)) return "\"Infinity\"";
            if (double.IsNegativeInfinity(v)) return "\"-Infinity\"";
            // PyYAML 1.2 / safe_load: "1E-08" is a string; need a decimal point in mantissa.
            double abs = Math.Abs(v);
            if (abs != 0.0 && (abs < 1e-4 || abs >= 1e15))
                return v.ToString("0.0##############e+0", CultureInfo.InvariantCulture);
            string s = v.ToString("0.#############################", CultureInfo.InvariantCulture);
            if (s.IndexOf('.') < 0 && s.IndexOf('e') < 0 && s.IndexOf('E') < 0)
                s += ".0";
            return s;
        }

        private static string YamlScalar(string s)
        {
            if (s == null) return "''";
            if (s.Length == 0) return "''";
            bool needsQuote = s.IndexOfAny(new[] { ':', '#', '{', '}', '[', ']', ',', '&', '*', '!', '|', '>', '\'', '"', '%' }) >= 0
                || s.StartsWith(" ") || s.EndsWith(" ") || s == "null" || s == "true" || s == "false"
                || s == "NaN" || s == "Infinity" || s == "-Infinity";
            if (!needsQuote) return s;
            return "'" + s.Replace("'", "''") + "'";
        }
    }
}
