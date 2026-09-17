using System;
using System.Collections;
using System.IO;
using System.Reflection;
using System.Runtime.Serialization;
using System.Runtime.Serialization.Formatters.Binary;
using VirtualLabAPI.Core.Materials;

namespace VlCatalogInspector
{
    /// <summary>
    /// Load .ctlg via BinaryFormatter + API binder.
    /// Must use typeof(MaterialsCatalog).Assembly (not a second LoadFrom).
    /// </summary>
    internal static class CatalogLoader
    {
        private const string MaterialsRel = @"Catalogs\MaterialsCatalog_LightTrans_Defined.ctlg";
        private const string CoatingsRel = @"Catalogs\CoatingsCatalog_LightTrans_Defined.ctlg";
        private const string InterfacesRel = @"Catalogs\InterfacesCatalog_LightTrans_Defined.ctlg";
        private const string BoundariesRel = @"Catalogs\BoundaryResponseCatalog_LightTrans_Defined.ctlg";
        private const string ApiDllName = "VirtualLabAPI.dll";

        public static MaterialsCatalog LoadMaterialsCatalog(string installDir)
        {
            object root = LoadCtlgRoot(installDir, MaterialsRel);
            var catalog = root as MaterialsCatalog;
            if (catalog == null)
                throw new InvalidOperationException(
                    "catalog root is " + (root != null ? root.GetType().FullName : "null") +
                    ", expected MaterialsCatalog");
            return catalog;
        }

        public static CatalogSlice LoadCoatings(string installDir)
        {
            return LoadSlice(installDir, CoatingsRel);
        }

        public static CatalogSlice LoadInterfaces(string installDir)
        {
            return LoadSlice(installDir, InterfacesRel);
        }

        public static CatalogSlice LoadBoundaries(string installDir)
        {
            return LoadSlice(installDir, BoundariesRel);
        }

        private static CatalogSlice LoadSlice(string installDir, string catalogRel)
        {
            object root = LoadCtlgRoot(installDir, catalogRel);
            object[] entries = TryGetEntries(root);
            string[] names = TryGetEntryNames(entries);
            return new CatalogSlice
            {
                Root = root,
                Entries = entries ?? new object[0],
                Names = names ?? new string[0],
            };
        }

        private static object LoadCtlgRoot(string installDir, string catalogRel)
        {
            if (string.IsNullOrWhiteSpace(installDir))
                throw new ArgumentException("installDir is required");

            string apiPath = Path.Combine(installDir, ApiDllName);
            string ctlgPath = Path.Combine(installDir, catalogRel);
            if (!File.Exists(apiPath))
                throw new FileNotFoundException("VirtualLabAPI.dll not found", apiPath);
            if (!File.Exists(ctlgPath))
                throw new FileNotFoundException("catalog not found", ctlgPath);

            AppDomain.CurrentDomain.AssemblyResolve += (sender, args) =>
            {
                try
                {
                    var an = new AssemblyName(args.Name);
                    if (string.Equals(an.Name, "VirtualLabAPI", StringComparison.OrdinalIgnoreCase))
                        return Assembly.LoadFrom(apiPath);
                    string candidate = Path.Combine(installDir, an.Name + ".dll");
                    if (File.Exists(candidate))
                        return Assembly.LoadFrom(candidate);
                }
                catch { }
                return null;
            };

            Assembly apiAsm = typeof(MaterialsCatalog).Assembly;
            var formatter = new BinaryFormatter { Binder = new VlSerializationBinder(apiAsm) };
            using (FileStream fs = File.OpenRead(ctlgPath))
                return formatter.Deserialize(fs);
        }

        private static object[] TryGetEntries(object root)
        {
            if (root == null) return null;
            try
            {
                PropertyInfo p = root.GetType().GetProperty("Entries", BindingFlags.Instance | BindingFlags.Public);
                if (p == null) return null;
                object entries = p.GetValue(root, null);
                var arr = entries as Array;
                if (arr != null)
                {
                    var copy = new object[arr.Length];
                    for (int i = 0; i < arr.Length; i++)
                        copy[i] = arr.GetValue(i);
                    return copy;
                }
                var list = entries as ICollection;
                if (list != null)
                {
                    var copy = new object[list.Count];
                    int i = 0;
                    foreach (object item in list)
                        copy[i++] = item;
                    return copy;
                }
            }
            catch { }
            return null;
        }

        private static string[] TryGetEntryNames(object[] entries)
        {
            if (entries == null) return null;
            var names = new string[entries.Length];
            for (int i = 0; i < entries.Length; i++)
            {
                object e = entries[i];
                if (e == null) { names[i] = "<null>"; continue; }
                try
                {
                    PropertyInfo np = e.GetType().GetProperty("Name", BindingFlags.Instance | BindingFlags.Public);
                    object nv = np != null ? np.GetValue(e, null) : null;
                    names[i] = nv != null ? nv.ToString() : e.GetType().Name;
                }
                catch
                {
                    names[i] = e.GetType().Name;
                }
            }
            return names;
        }

        private sealed class VlSerializationBinder : SerializationBinder
        {
            private readonly Assembly _apiAssembly;

            public VlSerializationBinder(Assembly apiAssembly)
            {
                _apiAssembly = apiAssembly ?? throw new ArgumentNullException(nameof(apiAssembly));
            }

            public override Type BindToType(string assemblyName, string typeName)
            {
                if (!string.IsNullOrEmpty(assemblyName) &&
                    assemblyName.IndexOf("VirtualLabAPI", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    Type t = _apiAssembly.GetType(typeName);
                    if (t != null) return t;
                }
                return Type.GetType(string.IsNullOrEmpty(assemblyName) ? typeName : typeName + ", " + assemblyName);
            }
        }
    }

    internal sealed class CatalogSlice
    {
        public object Root;
        public object[] Entries;
        public string[] Names;
    }
}
