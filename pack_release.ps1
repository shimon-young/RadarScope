<#
.SYNOPSIS
    RadarScope release packager (Windows) - builds the distributable zip.

.DESCRIPTION
    Copies ONLY the files that ship, then verifies the staged tree before
    zipping. Explicitly excluded:

      * model weights (ckpt\*.pth) and ckpt\bert-base-chinese\   ~3.6 GB
      * the demo patient case  data\demo_cases\                  ~94 MB
      * the Python virtual environment  RADAR_inference\env\
      * logs, results (may contain admin_auth.json), caches, editor files
      * .orig / .bak / .rej leftovers

    Files that MUST be present are verified before the zip is written:
    root LICENSE, THIRD_PARTY_LICENSES.md, and the vendored
    dynamic_network_architectures LICENSE + NOTICE (Apache-2.0 / BSD-3-Clause
    attribution obligations).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File pack_release.ps1
    powershell -ExecutionPolicy Bypass -File pack_release.ps1 -OutDir D:\out
#>
[CmdletBinding()]
param(
    [string]$OutDir = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# $PSScriptRoot is not populated while param defaults are evaluated, and is
# empty when the file is dot-sourced, so resolve the root separately.
$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $root) { $root = (Get-Location).Path }
if (-not $OutDir) { $OutDir = Join-Path $root 'dist' }

function Say  ($m) { Write-Host $m }
function Ok   ($m) { Write-Host "  [ok]   $m" -ForegroundColor Green }
function Warn2($m) { Write-Host "  [warn] $m" -ForegroundColor Yellow }
function Bad  ($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Head ($m) { Write-Host "`n$m" -ForegroundColor Cyan }

Say '============================================================'
Say ' RadarScope release packager'
Say " Source: $root"
Say " Output: $OutDir"
Say '============================================================'

# ---------------------------------------------------------------- preflight
$skipped = [System.Collections.Generic.List[string]]::new()

$weights = @(Get-ChildItem -Path (Join-Path $root 'ckpt') -Filter '*.pth' -ErrorAction SilentlyContinue)
if ($weights) {
    Warn2 "model weights present in ckpt\*.pth ($([math]::Round(($weights | Measure-Object Length -Sum).Sum/1GB,2)) GB) - NOT packed"
    $skipped.Add('model weights (*.pth)')
}
foreach ($d in @('ckpt\bert-base-chinese', 'data\demo_cases')) {
    if (Test-Path (Join-Path $root $d)) {
        Warn2 "$d present - NOT packed"
        $skipped.Add($d)
    }
}
foreach ($d in @('RADAR_inference\env', 'results', 'RADAR_inference\logs')) {
    if (Test-Path (Join-Path $root $d)) {
        Warn2 "$d present - NOT packed"
        $skipped.Add($d)
    }
}
$junk = @(Get-ChildItem -Path $root -Recurse -Include '*.orig','*.bak','*.rej' -File -ErrorAction SilentlyContinue |
          Where-Object { $_.FullName -notmatch '\\env\\|\\\.workbuddy\\' })
if ($junk) {
    Warn2 "leftover backup files found: $((($junk | ForEach-Object Name) -join ', '))"
    $skipped.Add('*.orig / *.bak / *.rej')
}

# ------------------------------------------------------------------ staging
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("radarscope_pack_" + [guid]::NewGuid().ToString('N').Substring(0,8))
Head '[1/4] Staging distributable files...'
New-Item -ItemType Directory -Path $stage -Force | Out-Null

$staged = 0
function Stage-Copy {
    param([string]$RelFrom, [string]$RelTo)
    $src = Join-Path $root $RelFrom
    $dst = Join-Path $stage $RelTo
    if (-not (Test-Path $src)) { return }
    # Always create the destination directory: Copy-Item with a wildcard
    # source silently copies nothing if the target folder does not exist yet.
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    try {
        Copy-Item -Path $src -Destination $dst -Force -ErrorAction Stop
        $script:staged += @(Get-ChildItem -Path $dst -File -ErrorAction SilentlyContinue).Count - 0
    } catch {
        Bad "copy failed: $RelFrom -> $RelTo ($($_.Exception.Message))"
    }
}

# top level
foreach ($f in @('README.md','LICENSE','THIRD_PARTY_LICENSES.md','requirements-desktop.txt','setup_env.bat','setup_env.sh')) {
    Stage-Copy $f ''
}
Stage-Copy 'docs\*.md'    'docs'
Stage-Copy 'docs\*.png'   'docs'

# ckpt: the three small text embeddings + bert-base-uncased vocabulary
Stage-Copy 'ckpt\infer_text_embedding_*.pt' 'ckpt'
foreach ($f in @('config.json','special_tokens_map.json','tokenizer_config.json','vocab.txt')) {
    Stage-Copy "ckpt\bert-base-uncased\$f" 'ckpt\bert-base-uncased'
}

# inference service
foreach ($f in @('service.py','inference_demo.py','items146.py','items_merlin20.py','merlin_prompts.py')) {
    Stage-Copy "RADAR_inference\$f" 'RADAR_inference'
}
Stage-Copy 'RADAR_inference\radar\*.py'         'RADAR_inference\radar'
Stage-Copy 'RADAR_inference\radar\engine\*.py'  'RADAR_inference\radar\engine'
Stage-Copy 'RADAR_inference\deploy\*'            'RADAR_inference\deploy'
Stage-Copy 'RADAR_inference\scripts\*.py'        'RADAR_inference\scripts'

# vendored third-party: LICENSE + NOTICE are attribution requirements, not optional.
# Copy the whole tree recursively -- architectures/ building_blocks/ initialization/
# are separate packages and are imported as such.
$vendored = Join-Path $root 'RADAR_inference\dynamic_network_architectures'
if (Test-Path $vendored) {
    $vDst = Join-Path $stage 'RADAR_inference\dynamic_network_architectures'
    New-Item -ItemType Directory -Path $vDst -Force | Out-Null
    # .py only: never carry caches or editor droppings into the archive
    Get-ChildItem -Path $vendored -Recurse -Filter '*.py' -File |
        ForEach-Object {
            $rel = $_.FullName.Substring($vendored.Length).TrimStart('\')
            $target = Join-Path $vDst $rel
            New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
            Copy-Item $_.FullName $target -Force
        }
    Copy-Item (Join-Path $vendored 'LICENSE') $vDst -Force
    Copy-Item (Join-Path $vendored 'NOTICE')  $vDst -Force
}

# frontend build output (embeds Cornerstone3D / VTK.js: MIT / BSD-3-Clause)
Stage-Copy 'frontend\dist\*.html'        'frontend\dist'
Stage-Copy 'frontend\dist\assets\*.js'   'frontend\dist\assets'
Stage-Copy 'frontend\dist\assets\*.css'  'frontend\dist\assets'

Say "  staged $(@(Get-ChildItem -Path $stage -Recurse -File).Count) file(s)"

# ----------------------------------------------------------------- verify
Head '[2/4] Verifying the staged tree...'
$fail = $false

# nothing forbidden may have slipped in
$forbidden = @(
    @{ Path = 'ckpt\*.pth';                Label = 'model weight file' },
    @{ Path = 'ckpt\bert-base-chinese';    Label = 'bert-base-chinese' },
    @{ Path = 'data\demo_cases';           Label = 'demo patient case' },
    @{ Path = 'RADAR_inference\env';       Label = 'virtualenv' },
    @{ Path = 'results';                   Label = 'results (admin creds)' }
)
foreach ($f in $forbidden) {
    if (Get-ChildItem -Path (Join-Path $stage $f.Path) -Recurse -Force -ErrorAction SilentlyContinue) {
        Bad "forbidden content staged: $($f.Label)"; $fail = $true
    } else {
        Ok "excluded: $($f.Label)"
    }
}

# required attribution / legal files must be present
$required = @(
    @{ Path = 'LICENSE';                                                  Label = 'root LICENSE (CC BY-NC-SA 4.0)' },
    @{ Path = 'THIRD_PARTY_LICENSES.md';                                   Label = 'THIRD_PARTY_LICENSES.md' },
    @{ Path = 'README.md';                                                 Label = 'README.md' },
    @{ Path = 'ckpt\infer_text_embedding_radar.pt';                        Label = 'main text embedding' },
    @{ Path = 'ckpt\infer_text_embedding_merlin_en.pt';                    Label = 'plus text embedding' },
    @{ Path = 'ckpt\bert-base-uncased\vocab.txt';                         Label = 'plus BERT vocabulary' },
    @{ Path = 'RADAR_inference\dynamic_network_architectures\LICENSE';     Label = 'vendored LICENSE (Apache-2.0)' },
    @{ Path = 'RADAR_inference\dynamic_network_architectures\NOTICE';      Label = 'vendored NOTICE (Apache-2.0 4(d))' },
    @{ Path = 'frontend\dist\index.html';                                  Label = 'frontend entry' }
)
foreach ($r in $required) {
    if (Test-Path (Join-Path $stage $r.Path)) { Ok "present: $($r.Label)" }
    else { Bad "MISSING: $($r.Label)  [$($r.Path)]"; $fail = $true }
}

if ($fail) {
    Write-Host "`n[ABORT] Verification failed. Nothing was zipped." -ForegroundColor Red
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}

# Completeness check: every importable vendored .py must be present, otherwise
# the service will fail at runtime with a ModuleNotFoundError.
Head '[2b] Checking vendored module completeness...'
$vendSrc = @(Get-ChildItem -Path (Join-Path $root 'RADAR_inference\dynamic_network_architectures') -Recurse -Filter '*.py' -File -ErrorAction SilentlyContinue)
$vendDst = @(Get-ChildItem -Path (Join-Path $stage 'RADAR_inference\dynamic_network_architectures') -Recurse -Filter '*.py' -File -ErrorAction SilentlyContinue)
if ($vendSrc.Count -gt 0) {
    if ($vendDst.Count -eq $vendSrc.Count) {
        Ok "vendored modules complete: $($vendDst.Count)/$($vendSrc.Count)"
    } else {
        Bad "vendored modules incomplete: $($vendDst.Count)/$($vendSrc.Count) - runtime ImportError likely"
        $srcNames = $vendSrc | ForEach-Object { $_.FullName.Substring((Join-Path $root 'RADAR_inference\dynamic_network_architectures').Length) }
        $dstNames = $vendDst | ForEach-Object { $_.FullName.Substring((Join-Path $stage 'RADAR_inference\dynamic_network_architectures').Length) }
        ($srcNames | Where-Object { $dstNames -notcontains $_ }) | ForEach-Object { Write-Host "         missing:$_" }
        $fail = $true
    }
}
if ($fail) {
    Write-Host "`n[ABORT] Vendored module check failed. Nothing was zipped." -ForegroundColor Red
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
    exit 1
}

# -------------------------------------------------------------------- zip
Head '[3/4] Zipping...'
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
# Package name carries no platform suffix on purpose: the archive holds only
# platform-neutral files (both the .bat and the .sh launchers ship), so the
# same build runs on Windows and Linux.
$zip = Join-Path $OutDir 'RadarScope.zip'
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -Force

# ------------------------------------------------------------------ report
Head '[4/4] Done.'
$zi = Get-Item $zip
$mb = [math]::Round($zi.Length / 1MB, 2)
Ok "$($zi.Name)  =  $mb MB"

# confirm the archive really excludes the big stuff
$entries = [System.IO.Compression.ZipFile]::OpenRead($zip)
$bad = @($entries.Entries | Where-Object {
    $_.FullName -match '\.pth$|demo_cases|bert-base-chinese|/env/|^results/'
})
$entries.Dispose()
if ($bad.Count) {
    Write-Host "  [FAIL] archive contains $($bad.Count) forbidden entr(y/ies):" -ForegroundColor Red
    $bad | Select-Object -First 10 -ExpandProperty FullName | ForEach-Object { Write-Host "         $_" }
    exit 1
}
Ok 'archive re-verified: no weights, no patient data, no venv'

# ------------------------------------------------- repo/dist consistency
# The zip is a whitelist; .gitignore is a blacklist. They drift apart easily,
# and the failure mode is nasty: a GitHub-only release would start the service
# but serve no page. This project ships no frontend sources, so frontend/dist
# cannot be rebuilt and MUST be tracked. Verify the two agree before shipping.
Head '[4b] Checking .gitignore vs archive consistency...'
$gitDir = Join-Path ([System.IO.Path]::GetTempPath()) ("radarscope_gitcheck_" + [guid]::NewGuid().ToString('N').Substring(0,8))
$tracked = Join-Path $gitDir 'tracked.txt'
try {
    New-Item -ItemType Directory -Path $gitDir -Force | Out-Null
    & git init -q $gitDir 2>$null
    $add = & git --git-dir="$gitDir\.git" --work-tree="$root" add -An 2>$null
    if (-not $add) {
        Warn2 'could not enumerate tracked files (git unavailable?) -- skipping repo check'
    } else {
        $trackedSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach ($line in $add) {
            # git quotes paths on some platforms: "add 'path/to/x.py'" (and
            # sometimes double quotes). Strip the prefix AND the quotes, or
            # every path keeps a stray quote and nothing ever matches.
            $p = $line -replace '^add\s+', ''
            $p = $p.Trim()
            $p = $p.Trim("'", '"', [char]0x2018, [char]0x2019, [char]0x201C, [char]0x201D)
            [void]$trackedSet.Add(($p -replace '\\','/'))
        }
        $zipSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        $zr = [System.IO.Compression.ZipFile]::OpenRead($zip)
        foreach ($e in $zr.Entries) { if ($e.Name) { [void]$zipSet.Add(($e.FullName -replace '\\','/')) } }
        $zr.Dispose()

        $missing = @($zipSet | Where-Object { -not $trackedSet.Contains($_) })
        if ($missing.Count) {
            Bad "these ship in the zip but are NOT tracked by git -- a GitHub-only release would be incomplete:"
            $missing | Select-Object -First 12 | ForEach-Object { Write-Host "         $_" }
            exit 1
        }
        Ok "every shipped file is tracked by git ($($zipSet.Count) entries)"

        # Never let .gitattributes itself fall out of tracking: if it is
        # untracked the eol locks never apply, Windows users get CRLF .sh
        # files, and setup_env.sh breaks on Linux. This regressed once.
        foreach ($must in @('.gitattributes', '.gitignore')) {
            if ($trackedSet.Contains($must)) { Ok "tracked: $must" }
            else { Bad "$must is NOT tracked -- line-ending / ignore rules would be inactive"; $fail = $true }
        }

        # Nothing sensitive may ever be tracked.
        $banned = @(
            @{ Rx = '\.(nii|nii\.gz|dcm|nrrd|mha)$'; Label = 'medical image' },
            @{ Rx = 'admin_auth\.json$';            Label = 'admin credentials' },
            @{ Rx = '^RADAR_inference/env/';        Label = 'virtualenv' }
        )
        foreach ($b in $banned) {
            $hit = @($trackedSet | Where-Object { $_ -match $b.Rx })
            if ($hit) { Bad "tracked but must never be: $($b.Label) -> $($hit -join ', ')"; $fail = $true }
            else { Ok "not tracked: $($b.Label)" }
        }

        if ($fail) { exit 1 }
    }
} finally {
    Remove-Item $gitDir -Recurse -Force -ErrorAction SilentlyContinue
}

Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue

if ($skipped.Count) {
    Write-Host "`n  Skipped from this build:" -ForegroundColor Yellow
    $skipped | ForEach-Object { Write-Host "    - $_" }
    Write-Host '  These files still exist in the source tree (not deleted).' -ForegroundColor Yellow
    Write-Host '  Ship the generated zip rather than zipping the source folder.' -ForegroundColor Yellow
}
Write-Host ''
exit 0
