[CmdletBinding()]
param(
    [string]$MetaEditor = 'C:\Program Files\MetaTrader 5\MetaEditor64.exe',
    [string]$StageDirectory = (Join-Path ([System.IO.Path]::GetTempPath()) ('agi-native-observer-' + [guid]::NewGuid().ToString('N')))
)
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$stage = [System.IO.Path]::GetFullPath($StageDirectory)
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$workspacePrefix = $projectRoot.TrimEnd('\') + '\'
if (-not ($stage.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -or $stage.StartsWith($workspacePrefix, [StringComparison]::OrdinalIgnoreCase))) {
    throw 'Staging must be a new directory inside the system temporary directory or this worktree.'
}
if (Test-Path -LiteralPath $stage) { throw 'Staging must not already exist.' }
if (-not (Test-Path -LiteralPath $MetaEditor -PathType Leaf)) { throw 'MetaEditor compiler not found.' }
$compiler = [System.IO.Path]::GetFullPath($MetaEditor)
if ([System.IO.Path]::GetFileName($compiler) -ine 'MetaEditor64.exe') { throw 'Only the MetaEditor compiler is supported.' }
$mqlRoot = Join-Path $stage 'MQL5'
New-Item -ItemType Directory -Path (Join-Path $mqlRoot 'Experts'), (Join-Path $mqlRoot 'Scripts'), (Join-Path $mqlRoot 'Include') | Out-Null
$sourceRoot = Join-Path $projectRoot 'src\mt5'
$sources = @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -File | Where-Object { $_.Extension -in '.mq5','.mqh' })
$sourceHashes = [ordered]@{}
foreach ($source in $sources) {
    $relative = [System.IO.Path]::GetRelativePath($sourceRoot, $source.FullName)
    $destination = Join-Path $mqlRoot $relative
    New-Item -ItemType Directory -Force -Path ([System.IO.Path]::GetDirectoryName($destination)) | Out-Null
    Copy-Item -LiteralPath $source.FullName -Destination $destination
    $sourceHashes[$relative.Replace('\','/')] = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
}
$harness = Join-Path $projectRoot 'tests\mt5\ObservationPolicyHarness.mq5'
Copy-Item -LiteralPath $harness -Destination (Join-Path $mqlRoot 'Scripts\ObservationPolicyHarness.mq5')
$sourceHashes['Scripts/ObservationPolicyHarness.mq5'] = (Get-FileHash -LiteralPath $harness -Algorithm SHA256).Hash.ToLowerInvariant()
$results = @()
foreach ($relative in @('Experts\AGI_STYLE_FOREX_BOT_MT5.mq5', 'Scripts\ObservationPolicyHarness.mq5')) {
    $source = Join-Path $mqlRoot $relative
    $arguments = @('/compile:"' + $source + '"', '/include:"' + $mqlRoot + '"', '/log')
    $process = Start-Process -FilePath $compiler -ArgumentList $arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) {
        $process.Kill()
        throw 'Compiler timeout; only this compiler process was stopped.'
    }
    $log = [System.IO.Path]::ChangeExtension($source, '.log')
    $binary = [System.IO.Path]::ChangeExtension($source, '.ex5')
    if (-not (Test-Path -LiteralPath $log)) { throw 'Compiler produced no diagnostic log.' }
    $diagnostics = Get-Content -LiteralPath $log -Raw
    $clean = $diagnostics -match '0 errors, 0 warnings' -and (Test-Path -LiteralPath $binary -PathType Leaf)
    $results += [ordered]@{
        source = $relative.Replace('\','/'); clean_build = $clean; process_exit_code = $process.ExitCode
        log_sha256 = (Get-FileHash -LiteralPath $log -Algorithm SHA256).Hash.ToLowerInvariant()
        binary_sha256 = $(if (Test-Path -LiteralPath $binary) { (Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null })
    }
    if (-not $clean) {
        Write-Output $diagnostics
        throw ('Native compile did not complete without errors/warnings: ' + $relative)
    }
}
$manifest = [ordered]@{
    schema_version = 'native_compile_evidence_v1'; scope = 'NATIVE_OBSERVATION_ONLY'
    compiled_at_utc = [DateTime]::UtcNow.ToString('o'); compiler_version = (Get-Item -LiteralPath $compiler).VersionInfo.FileVersion
    compiler_sha256 = (Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash.ToLowerInvariant()
    build_script_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    source_hashes = $sourceHashes; results = $results
    harness_executed = $false; terminal_started = $false; installed_to_terminal = $false
    execution_authorized = $false; release_status = 'BLOCKED'
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $stage 'compile-manifest.json') -Encoding utf8
Write-Output ('Native compilation verified; evidence retained at: ' + $stage)
