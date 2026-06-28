# Export VirtualLab catalog to CSV + meta.json for WSL YAML conversion.
# Windows only (loads VirtualLabAPI.dll). Does NOT require Python.
param(
    [string]$InstallDir = "C:\Program Files\Wyrowski Photonics\VirtualLab Fusion (7.5.0) Trial",
    [Parameter(Mandatory = $true)]
    [string]$OutRoot,
    [string]$IndexRoot = "",
    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"
if (-not $IndexRoot) {
    $IndexRoot = Split-Path $OutRoot -Parent
}
$indexDir = Join-Path $IndexRoot "materials_export"
New-Item -ItemType Directory -Force -Path $OutRoot, $indexDir | Out-Null

$dll  = Join-Path $InstallDir "VirtualLabAPI.dll"
$ctlg = Join-Path $InstallDir "Catalogs\MaterialsCatalog_LightTrans_Defined.ctlg"
if (-not (Test-Path $dll))  { throw "VirtualLabAPI.dll not found: $dll" }
if (-not (Test-Path $ctlg)) { throw "Materials catalog not found: $ctlg" }

Add-Type -TypeDefinition @'
using System; using System.IO; using System.Reflection;
using System.Runtime.Serialization; using System.Runtime.Serialization.Formatters.Binary;
public class VLBinder : SerializationBinder {
    Assembly _a; public VLBinder(Assembly a){_a=a;}
    public override Type BindToType(string an, string tn){
        if(an.StartsWith("VirtualLabAPI")) return _a.GetType(tn);
        return Type.GetType(tn+", "+an);
    }
}
public static class VLLoader {
    public static object Load(string dll, string ctlg) {
        var asm = Assembly.LoadFrom(dll);
        var fmt = new BinaryFormatter { Binder = new VLBinder(asm) };
        using (var fs = File.OpenRead(ctlg)) return fmt.Deserialize(fs);
    }
}
'@

function Safe-DirName([string]$n) {
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $n.ToCharArray()) {
        if ($ch -match '[a-zA-Z0-9_]') { [void]$sb.Append($ch) }
        else { [void]$sb.Append('_') }
    }
    $result = $sb.ToString()
    while ($result -match '__') { $result = $result -replace '__', '_' }
    $result = $result.Trim('_')
    if ($result.Length -eq 0) { $result = 'material' }
    if ($result -match '^[0-9]') { $result = "m_$result" }
    if ($result.Length -gt 180) { $result = $result.Substring(0, 180).Trim('_') }
    return $result
}

function Get-UniqueDirName([string]$base, [hashtable]$used) {
    $name = $base
    $i = 2
    while ($used.ContainsKey($name)) {
        $suffix = "_$i"
        $maxLen = 180 - $suffix.Length
        $name = $base.Substring(0, [Math]::Min($base.Length, $maxLen)).TrimEnd('_') + $suffix
        $i++
    }
    $used[$name] = $true
    return $name
}

function Format-CsvValue([double]$v) {
    $ci = [System.Globalization.CultureInfo]::InvariantCulture
    return $v.ToString('0.000000e+00', $ci).Replace('E', 'e')
}

function Read-DataArray($da) {
    if ($null -eq $da) { return $null }
    $n = [int]$da.NoOfDataPoints
    if ($n -le 0) { return $null }
    $wl = New-Object double[] $n
    if ($da.IsEquidistant) {
        $start = [double]$da.CoordinateOfFirstDataPoint
        $step  = [double]$da.SamplingDistance
        for ($i = 0; $i -lt $n; $i++) { $wl[$i] = $start + $i * $step }
    } else {
        $nc = $da.NonequidistantCoordinates
        for ($i = 0; $i -lt $n; $i++) { $wl[$i] = [double]$nc.get_Item([int64]$i) }
    }
    $field = $da.Data.get_Item(0)
    $vals = New-Object double[] $n
    for ($i = 0; $i -lt $n; $i++) {
        $raw = $field.get_Item([int64]$i)
        if ($field.GetType().Name -eq 'CFieldDerivative1DReal') {
            $vals[$i] = [double]$raw
        } else {
            $vals[$i] = [double]$raw.GetType().GetField('Re').GetValue($raw)
        }
    }
    return @{ WlM = $wl; Values = $vals; Count = $n }
}

function Make-Header([string]$title, [string]$dataLabel, [string]$dataUnits, [int]$count) {
    return '{"title":"' + $title + '","type":"xy","y_label":"Wavelength","data_label":"' + $dataLabel +
           '","y_units":"nm","y_mul":1000000000.0,"data_units":"' + $dataUnits +
           '","icon":"mat_file","time ":0.0,"Vexternal":0.0,"x_len":1,"y_len":' + $count +
           ',"z_len":1,"cols":"yd"}'
}

function Write-YdCsv([string]$path, [string]$header, [double[]]$wlM, [double[]]$vals) {
    $sw = [IO.StreamWriter]::new($path, $false, [Text.Encoding]::UTF8)
    $sw.WriteLine("#simulation_toolkits_csv $header*")
    for ($i = 0; $i -lt $wlM.Length; $i++) {
        $sw.WriteLine((Format-CsvValue $wlM[$i]) + "`t" + (Format-CsvValue $vals[$i]))
    }
    $sw.Close()
}

function Get-DefaultWlGrid {
    $pts = New-Object System.Collections.Generic.List[double]
    for ($nm = 300.0; $nm -le 2500.0; $nm += 10.0) { [void]$pts.Add($nm * 1e-9) }
    return $pts.ToArray()
}

function Export-Material($mat, [string]$dir, [string]$originalName) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $p = @($mat.Parameters | ForEach-Object { [double]$_ })
    $nData = Read-DataArray $mat.SampledRefractiveIndex
    $aData = Read-DataArray $mat.SampledAbsorptionCoeff
    $hasAlpha = $false
    $hasSampledN = $null -ne $nData
    $npts = 0

    $meta = [ordered]@{
        original_name       = $originalName
        dispersion_formula  = [string]$mat.DispersionFormula
        absorption_formula  = [string]$mat.AbsorptionFormula
        parameters          = $p
        constant_absorption = [double]$mat.ConstantAbsorptionCoeff
        wl_min_um           = 0.3
        wl_max_um           = 2.5
        has_sampled_n       = $hasSampledN
    }
    ($meta | ConvertTo-Json -Depth 6) | Out-File (Join-Path $dir "meta.json") -Encoding utf8

    if ($hasSampledN) {
        $wlM = $nData.WlM
        $nVals = $nData.Values
        $npts = $wlM.Length
        $nHeader = Make-Header "Wavelength - Refractive index" "Refractive index" "au" $wlM.Length
        Write-YdCsv (Join-Path $dir "n.csv") $nHeader $wlM $nVals
    }

    if ($aData) {
        $alphaWl = $aData.WlM
        $alphaVals = $aData.Values
        $aHeader = Make-Header "Wavelength - Absorption" "Absorption" "m^{-1}" $alphaWl.Length
        Write-YdCsv (Join-Path $dir "alpha.csv") $aHeader $alphaWl $alphaVals
        $hasAlpha = $true
        if (-not $hasSampledN) { $npts = $alphaWl.Length }
    } elseif ([string]$mat.AbsorptionFormula -eq 'Constant' -and [double]$mat.ConstantAbsorptionCoeff -gt 0) {
        $wlM = if ($hasSampledN) { $nData.WlM } else { Get-DefaultWlGrid }
        $alphaVals = New-Object double[] $wlM.Length
        for ($i = 0; $i -lt $wlM.Length; $i++) { $alphaVals[$i] = [double]$mat.ConstantAbsorptionCoeff }
        $aHeader = Make-Header "Wavelength - Absorption" "Absorption" "m^{-1}" $wlM.Length
        Write-YdCsv (Join-Path $dir "alpha.csv") $aHeader $wlM $alphaVals
        $hasAlpha = $true
        if (-not $hasSampledN) { $npts = $wlM.Length }
    }

    return @{
        HasAlpha    = $hasAlpha
        HasSampledN = $hasSampledN
        Formula     = [string]$mat.DispersionFormula
        Npts        = $npts
    }
}

Write-Host "Loading catalog from $ctlg ..."
$catalog = [VLLoader]::Load($dll, $ctlg)
$targets = @($catalog.Entries | ForEach-Object { $_.Name })
if ($Limit -gt 0) { $targets = $targets[0..([Math]::Min($Limit, $targets.Count) - 1)] }

$byName = @{}
foreach ($e in $catalog.Entries) { $byName[$e.Name] = $e }

$ok = 0; $withAlpha = 0; $withSampledN = 0; $err = 0
$usedDirs = @{}
$index = New-Object System.Collections.Generic.List[string]
$index.Add("original_name,dir_name,dispersion_formula,has_sampled_n,has_alpha,n_points")

foreach ($name in $targets) {
    if (-not $byName.ContainsKey($name)) { Write-Host "MISSING: $name"; continue }
    $dirName = Get-UniqueDirName (Safe-DirName $name) $usedDirs
    $dir = Join-Path $OutRoot $dirName
    try {
        $r = Export-Material $byName[$name] $dir $name
        $ok++
        if ($r.HasAlpha) { $withAlpha++ }
        if ($r.HasSampledN) { $withSampledN++ }
        $index.Add("$name,$dirName,$($r.Formula),$($r.HasSampledN),$($r.HasAlpha),$($r.Npts)")
        if ($ok % 200 -eq 0) { Write-Host "  $ok / $($targets.Count)" }
    } catch {
        $err++
        Write-Host "ERR: $name - $_"
        $index.Add("$name,$dirName,error,False,False,0")
    }
}

$indexPath = Join-Path $indexDir "index.csv"
$index | Out-File $indexPath -Encoding utf8
Write-Host "Done: $ok materials ($withSampledN sampled-n, $withAlpha with alpha), $err errors"
Write-Host "  materials -> $OutRoot"
Write-Host "  index     -> $indexPath"
exit 0
