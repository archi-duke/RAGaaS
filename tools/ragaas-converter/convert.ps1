<#
  ragaas-converter: extract plain text from a .docx / .pptx via Office COM automation.

  Office is used (instead of parsing the OOXML directly) because DRM-protected files
  (e.g. NASCA DRM: file header starts with "<## NASCA DRM FILE") can only be decrypted by
  the DRM agent hooked into the locally installed Office process.

  Usage:
    powershell -NoProfile -ExecutionPolicy Bypass -File convert.ps1 -Path <file> -Format docx|pptx -OutFile <json>

  Output (UTF-8 JSON written to -OutFile):
    success: { "ok": true,  "text": "...", "units": <pages|slides>, "unit": "page|slide" }
    failure: { "ok": false, "error": "..." }
  Exit code: 0 success, 2 failure.

  NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads BOM-less scripts as ANSI.
#>
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][ValidateSet('docx', 'pptx')][string]$Format,
    [Parameter(Mandatory = $true)][string]$OutFile
)

$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding $false

function Write-Result($obj) {
    $json = $obj | ConvertTo-Json -Depth 3 -Compress
    [System.IO.File]::WriteAllText($OutFile, $json, $utf8)
}

function Release($o) {
    if ($null -ne $o) {
        try { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($o) } catch {}
    }
}

# Word/PowerPoint use CR as paragraph separator, VT as manual line break,
# BEL as table cell marker, FF as page break.
function Normalize-Text([string]$t) {
    if ($null -eq $t) { return '' }
    $t = $t -replace "`r`a", "`t"
    $t = $t -replace "`a", ''
    $t = $t -replace "`f", "`n"
    $t = $t -replace "`v", "`n"
    $t = $t -replace "`r`n", "`n"
    $t = $t -replace "`r", "`n"
    $t = $t -replace '\n{3,}', "`n`n"
    return $t.Trim()
}

function Convert-Docx([string]$file) {
    $word = $null; $doc = $null
    try {
        # Word is multi-instance: New-Object always starts a private instance, safe to Quit.
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $word.DisplayAlerts = 0          # wdAlertsNone
        $word.AutomationSecurity = 3     # msoAutomationSecurityForceDisable (no macros)
        # Documents.Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles,
        #                PasswordDocument, PasswordTemplate, Revert, WritePasswordDocument,
        #                WritePasswordTemplate, Format, Encoding, Visible)
        # A dummy password makes password-protected docs fail fast instead of prompting.
        $doc = $word.Documents.Open($file, $false, $true, $false, 'x-no-password', '', $true, '', '', 0, [Type]::Missing, $false)
        $text = Normalize-Text $doc.Content.Text
        $pages = 0
        try { $pages = [int]$doc.ComputeStatistics(2) } catch {}   # wdStatisticPages
        return @{ ok = $true; text = $text; units = $pages; unit = 'page' }
    }
    finally {
        # Some Word COM methods take ByRef args ([ref] required in PowerShell) depending on the
        # interop path; try by-value first, then [ref]. 0 = wdDoNotSaveChanges.
        if ($null -ne $doc) {
            try { $doc.Close(0) } catch { try { $doc.Close([ref]0) } catch {} }
        }
        Release $doc
        if ($null -ne $word) {
            try { $word.Quit([ref]0) } catch { try { $word.Quit(0) } catch {} }
        }
        Release $word
    }
}

function Get-ShapeText($shape, [System.Collections.Generic.List[string]]$out) {
    try {
        if ($shape.Type -eq 6) {                                    # msoGroup
            foreach ($child in $shape.GroupItems) { Get-ShapeText $child $out }
            return
        }
        if ($shape.HasTable -eq -1) {
            $tbl = $shape.Table
            for ($r = 1; $r -le $tbl.Rows.Count; $r++) {
                $cells = @()
                for ($c = 1; $c -le $tbl.Columns.Count; $c++) {
                    $cells += (Normalize-Text $tbl.Cell($r, $c).Shape.TextFrame.TextRange.Text) -replace "`n", ' '
                }
                $out.Add(($cells -join "`t"))
            }
            return
        }
        if ($shape.HasSmartArt -eq -1) {
            foreach ($node in $shape.SmartArt.AllNodes) {
                $t = Normalize-Text $node.TextFrame2.TextRange.Text
                if ($t) { $out.Add($t) }
            }
            return
        }
        if ($shape.HasTextFrame -eq -1 -and $shape.TextFrame.HasText -eq -1) {
            $t = Normalize-Text $shape.TextFrame.TextRange.Text
            if ($t) { $out.Add($t) }
        }
    }
    catch {
        # Unsupported shape kinds (OLE, media, ...) are skipped.
    }
}

function Convert-Pptx([string]$file) {
    # PowerPoint is single-instance: if the user already has it open, New-Object attaches to
    # that instance and we must NOT Quit it.
    $wasRunning = @(Get-Process -Name POWERPNT -ErrorAction SilentlyContinue).Count -gt 0
    $app = $null; $pres = $null
    try {
        $app = New-Object -ComObject PowerPoint.Application
        try { $app.DisplayAlerts = 1 } catch {}                      # ppAlertsNone
        try { $app.AutomationSecurity = 3 } catch {}
        # Presentations.Open(FileName, ReadOnly, Untitled, WithWindow)  msoTrue=-1 msoFalse=0
        $pres = $app.Presentations.Open($file, -1, 0, 0)
        $sb = New-Object System.Text.StringBuilder
        $index = 0
        foreach ($slide in $pres.Slides) {
            $index++
            $lines = New-Object 'System.Collections.Generic.List[string]'
            foreach ($shape in $slide.Shapes) { Get-ShapeText $shape $lines }
            $notes = ''
            try {
                foreach ($ns in $slide.NotesPage.Shapes) {
                    if ($ns.Type -eq 14 -and $ns.PlaceholderFormat.Type -eq 2) {   # placeholder / ppPlaceholderBody
                        $notes = Normalize-Text $ns.TextFrame.TextRange.Text
                    }
                }
            } catch {}
            [void]$sb.AppendLine("## Slide $index")
            foreach ($l in $lines) { [void]$sb.AppendLine($l) }
            if ($notes) { [void]$sb.AppendLine("[Notes] $notes") }
            [void]$sb.AppendLine()
        }
        return @{ ok = $true; text = $sb.ToString().Replace("`r`n", "`n").Trim(); units = $index; unit = 'slide' }
    }
    finally {
        if ($null -ne $pres) { try { $pres.Close() } catch {} }
        Release $pres
        if ($null -ne $app -and -not $wasRunning) {
            try { if ($app.Presentations.Count -eq 0) { $app.Quit() } } catch {}
        }
        Release $app
    }
}

try {
    $full = (Resolve-Path -LiteralPath $Path).ProviderPath
    if ($Format -eq 'docx') { $res = Convert-Docx $full } else { $res = Convert-Pptx $full }
    Write-Result $res
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
    exit 0
}
catch {
    Write-Result @{ ok = $false; error = $_.Exception.Message }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
    exit 2
}
