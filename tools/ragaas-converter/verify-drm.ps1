<#
  verify-drm.ps1 - pre-check on a company PC (DRM agent installed and logged in).

  Question to answer: can Office open a DRM-protected file that was COPIED to a temp
  directory (the converter receives raw bytes from the browser and writes them to a new
  temp file), or only the original file?

  Usage (PowerShell, on the company PC):
    powershell -NoProfile -ExecutionPolicy Bypass -File verify-drm.ps1 -Path "C:\docs\sample.pptx"

  Runs convert.ps1 (same folder) twice:
    1) on the original path
    2) on a byte copy written to %TEMP%\ragaas-converter-verify\source.<ext>
  and prints whether each succeeded, the slide/page count and the first characters.

  NOTE: keep this file ASCII-only (Windows PowerShell 5.1 reads BOM-less scripts as ANSI).
#>
param([Parameter(Mandatory = $true)][string]$Path)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$convert = Join-Path $here 'convert.ps1'
if (-not (Test-Path $convert)) { throw "convert.ps1 not found next to this script: $convert" }

$src = (Resolve-Path -LiteralPath $Path).ProviderPath
$ext = [IO.Path]::GetExtension($src).TrimStart('.').ToLower()
if ($ext -ne 'docx' -and $ext -ne 'pptx') { throw "only .docx / .pptx supported (got .$ext)" }

$head = New-Object byte[] 32
$fs = [IO.File]::OpenRead($src)
try { [void]$fs.Read($head, 0, 32) } finally { $fs.Close() }
$headText = [Text.Encoding]::ASCII.GetString($head)
$isDrm = $headText.StartsWith('<## NASCA DRM FILE')
Write-Host ("File      : {0}" -f $src)
Write-Host ("Header    : {0}" -f ($headText -replace '[^\x20-\x7E]', '.'))
Write-Host ("DRM       : {0}" -f $isDrm)
Write-Host ''

$work = Join-Path $env:TEMP 'ragaas-converter-verify'
New-Item -ItemType Directory -Force -Path $work | Out-Null
$copy = Join-Path $work ("source." + $ext)
[IO.File]::WriteAllBytes($copy, [IO.File]::ReadAllBytes($src))

function Run-Case([string]$label, [string]$file) {
    $out = Join-Path $work ("result-" + $label + ".json")
    if (Test-Path $out) { Remove-Item $out -Force }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $convert -Path $file -Format $ext -OutFile $out | Out-Null
    $sw.Stop()
    if (-not (Test-Path $out)) {
        Write-Host ("[{0}] FAILED - no result file ({1:N1}s)" -f $label, $sw.Elapsed.TotalSeconds) -ForegroundColor Red
        return
    }
    $r = [IO.File]::ReadAllText($out, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ($r.ok) {
        $preview = $r.text.Substring(0, [Math]::Min(120, $r.text.Length)) -replace "`n", ' / '
        Write-Host ("[{0}] OK - {1} {2}(s), {3} chars, {4:N1}s" -f $label, $r.units, $r.unit, $r.text.Length, $sw.Elapsed.TotalSeconds) -ForegroundColor Green
        Write-Host ("        {0}" -f $preview)
    }
    else {
        Write-Host ("[{0}] FAILED - {1} ({2:N1}s)" -f $label, $r.error, $sw.Elapsed.TotalSeconds) -ForegroundColor Red
    }
}

Run-Case 'original' $src
Run-Case 'temp-copy' $copy

Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
Write-Host ''
Write-Host 'Expected for the converter to work: [temp-copy] OK.'
