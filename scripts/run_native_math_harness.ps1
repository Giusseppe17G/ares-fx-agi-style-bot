[CmdletBinding()]
param(
    [string]$InstallDirectory = 'C:\Program Files\MetaTrader 5',
    [string]$StageDirectory = (Join-Path ([IO.Path]::GetTempPath()) ('agi-native-math-' + [guid]::NewGuid().ToString('N'))),
    [ValidateRange(5,60)][int]$TimeoutSeconds = 45
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$stage = [IO.Path]::GetFullPath($StageDirectory)
$tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
if (-not $stage.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'A new staging directory inside system TEMP is required.' }
if (Test-Path -LiteralPath $stage) { throw 'Staging must not already exist.' }
$install = [IO.Path]::GetFullPath($InstallDirectory)
$compiler = Join-Path $install 'MetaEditor64.exe'
foreach ($name in @('MetaEditor64.exe','terminal64.exe','metatester64.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $install $name) -PathType Leaf)) { throw ('Installed public binary missing: ' + $name) }
}
function Get-Sha256([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Save-Manifest($Value, [string]$Path) { $Value | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding utf8 }

$mqlRoot = Join-Path $stage 'MQL5'
$wrapperDirectory = Join-Path $mqlRoot 'Experts\NativeMathHarness'
New-Item -ItemType Directory -Path $wrapperDirectory, (Join-Path $mqlRoot 'Include') | Out-Null
$sourceHashes = [ordered]@{}
$includeRoot = Join-Path $projectRoot 'src\mt5\Include'
foreach ($source in (Get-ChildItem -LiteralPath $includeRoot -Recurse -File | Where-Object { $_.Extension -eq '.mqh' })) {
    $relative = [IO.Path]::GetRelativePath($includeRoot, $source.FullName)
    $destination = Join-Path (Join-Path $mqlRoot 'Include') $relative
    New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($destination)) | Out-Null
    Copy-Item -LiteralPath $source.FullName -Destination $destination
    $sourceHashes['Include/' + $relative.Replace('\','/')] = Get-Sha256 $destination
}
$fixtureNames = @('ObservationPolicyHarness.mq5','ClosedBarWindowHarness.mq5','GeneratedClosedBarFixtures.mqh',
    'CoreIndicatorsHarness.mq5','GeneratedCoreIndicatorFixtures.mqh','NativeMathHarness.mq5')
foreach ($name in $fixtureNames) {
    $destination = Join-Path $wrapperDirectory $name
    Copy-Item -LiteralPath (Join-Path $projectRoot ('tests\mt5\' + $name)) -Destination $destination
    $sourceHashes['Experts/NativeMathHarness/' + $name] = Get-Sha256 $destination
}
$wrapperSource = Join-Path $wrapperDirectory 'NativeMathHarness.mq5'
$compileProcess = Start-Process -FilePath $compiler -ArgumentList @('/compile:"' + $wrapperSource + '"','/include:"' + $mqlRoot + '"','/log') -WindowStyle Hidden -PassThru
if (-not $compileProcess.WaitForExit(60000)) {
    $compileProcess.Kill()
    throw 'Only the owned compiler was stopped after timeout; terminal was not started.'
}
$compileLog = [IO.Path]::ChangeExtension($wrapperSource, '.log')
$compiledBinary = [IO.Path]::ChangeExtension($wrapperSource, '.ex5')
if (-not (Test-Path -LiteralPath $compileLog) -or -not (Test-Path -LiteralPath $compiledBinary)) { throw 'Wrapper compile evidence missing; terminal was not started.' }
# Anchored: an unanchored '0 errors, 0 warnings' also matches '10 errors, 0 warnings'.
if ((Get-Content -LiteralPath $compileLog -Raw) -notmatch '(?m)^Result: 0 errors, 0 warnings,') { throw 'Wrapper did not compile cleanly; terminal was not started.' }
$binary = Join-Path $mqlRoot 'Experts\NativeMathHarness.ex5'
Copy-Item -LiteralPath $compiledBinary -Destination $binary
$publicBinaries = [ordered]@{}
foreach ($name in @('terminal64.exe','metatester64.exe')) {
    $destination = Join-Path $stage $name
    Copy-Item -LiteralPath (Join-Path $install $name) -Destination $destination
    $publicBinaries[$name] = Get-Sha256 $destination
    if ($publicBinaries[$name] -ne (Get-Sha256 (Join-Path $install $name))) { throw 'Public binary copy hash mismatch.' }
}
$configPath = Join-Path $stage 'native-math.ini'
# No account database, profile, login, password or server is copied/configured.
# A loopback proxy discourages host network use; it is NOT a network sandbox.
$config = @'
[Common]
ProxyEnable=1
ProxyType=2
ProxyAddress=127.0.0.1:9
KeepPrivate=0
NewsEnable=0
CertInstall=0
[Experts]
Enabled=0
AllowLiveTrading=0
AllowDllImport=0
Account=1
Profile=1
[Tester]
Expert=NativeMathHarness.ex5
Model=3
Optimization=0
ForwardMode=0
Visual=0
UseLocal=1
UseRemote=0
UseCloud=0
ShutdownTerminal=1
'@
[IO.File]::WriteAllText($configPath, $config, [Text.UTF8Encoding]::new($false))
$parser = Join-Path $PSScriptRoot 'check_native_math_logs.py'
$manifestPath = Join-Path $stage 'native-math-manifest.json'
$manifest = [ordered]@{
    schema_version = 'native_math_run_v1'; scope = 'SYNTHETIC_NATIVE_FIXTURES_ONLY'
    status = 'PREPARED'; passed = $false; reason = 'NOT_STARTED'
    source_hashes = $sourceHashes; runner_sha256 = Get-Sha256 $PSCommandPath
    parser_sha256 = Get-Sha256 $parser; compiler_sha256 = Get-Sha256 $compiler
    compiler_version = (Get-Item -LiteralPath $compiler).VersionInfo.FileVersion
    compiler_exit_code = $compileProcess.ExitCode; compile_log_sha256 = Get-Sha256 $compileLog
    harness_ex5_sha256 = Get-Sha256 $binary; config_sha256 = Get-Sha256 $configPath
    public_binary_hashes = $publicBinaries; configured_model = 3; timeout_seconds = $TimeoutSeconds
    terminal_started = $false; terminal_exited = $false; terminal_exit_code = $null; timed_out = $false
    own_processes_stopped = @(); cleanup_verified = $false; terminal_version = (Get-Item -LiteralPath (Join-Path $stage 'terminal64.exe')).VersionInfo.FileVersion
    account_or_profile_copied = $false; credentials_configured = $false
    network_isolation_verified = $false; local_agents_only = $true
    execution_authorized = $false; full_pipeline_verified = $false; promotion_eligible = $false
}
Save-Manifest $manifest $manifestPath
$terminal = $null
$launchUtc = [DateTime]::UtcNow
$terminalPath = Join-Path $stage 'terminal64.exe'
$testerPath = Join-Path $stage 'metatester64.exe'
$ownedExecutablePaths = @($terminalPath, $testerPath)
try {
    # Recheck the immutable inputs immediately before launching the new copy.
    if ((Get-Sha256 $configPath) -ne $manifest.config_sha256 -or (Get-Sha256 $binary) -ne $manifest.harness_ex5_sha256) { throw 'Launch input hash mismatch.' }
    if ([IO.File]::ReadAllText($configPath) -cne $config) { throw 'Launch configuration differs from fixed math-only configuration.' }
    foreach ($name in $publicBinaries.Keys) {
        if ((Get-Sha256 (Join-Path $stage $name)) -ne $publicBinaries[$name]) { throw 'Launch executable hash mismatch.' }
    }
    $manifest.started_at_utc = $launchUtc.ToString('o')
    $manifest.status = 'RUNNING'
    Save-Manifest $manifest $manifestPath
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $terminal = Start-Process -FilePath $terminalPath -ArgumentList @('/portable','/config:"' + $configPath + '"') -WorkingDirectory $stage -WindowStyle Hidden -PassThru
    $manifest.terminal_started = $true
    while (-not $terminal.HasExited -and $timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        [void]$terminal.WaitForExit(500)
    }
    $manifest.elapsed_seconds = $timer.Elapsed.TotalSeconds
    $manifest.terminal_exited = $terminal.HasExited
    $manifest.timed_out = -not $terminal.HasExited
    if ($terminal.HasExited) { $manifest.terminal_exit_code = $terminal.ExitCode }
    $manifest.reason = $(if ($manifest.timed_out) { 'TERMINAL_TIMEOUT' } else { 'AWAITING_LOG_VERIFICATION' })
} catch {
    $manifest.reason = 'LAUNCH_OR_PROCESS_ERROR'
    $manifest.error_type = $_.Exception.GetType().FullName
} finally {
    # Match exact executables in this freshly created staging, never process names.
    $stopped = @()
    foreach ($processInfo in (Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath -in $ownedExecutablePaths })) {
        $owned = Get-Process -Id $processInfo.ProcessId -ErrorAction SilentlyContinue
        if ($null -ne $owned -and $owned.Path -in $ownedExecutablePaths -and $owned.StartTime.ToUniversalTime() -ge $launchUtc.AddSeconds(-1)) {
            Stop-Process -Id $owned.Id -Force
            [void]$owned.WaitForExit(3000)
            $stopped += [int]$owned.Id
        }
    }
    $manifest.own_processes_stopped = $stopped
    $remaining = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath -in $ownedExecutablePaths })
    $manifest.cleanup_verified = $remaining.Count -eq 0
    Save-Manifest $manifest $manifestPath
}
$logEvidencePath = Join-Path $stage 'native-math-log-evidence.json'
& py -3.14 -I -B $parser --stage $stage --output $logEvidencePath
$parserExit = $LASTEXITCODE
$manifest.parser_exit_code = $parserExit
if (Test-Path -LiteralPath $logEvidencePath) {
    $evidence = Get-Content -LiteralPath $logEvidencePath -Raw | ConvertFrom-Json
    $manifest.log_evidence_sha256 = Get-Sha256 $logEvidencePath
    $manifest.log_evidence_passed = $evidence.passed -eq $true
    if ($manifest.reason -eq 'AWAITING_LOG_VERIFICATION') { $manifest.reason = $evidence.reason }
} else { $manifest.log_evidence_passed = $false }
$bindingsUnchanged = (Get-Sha256 $configPath) -eq $manifest.config_sha256 -and (Get-Sha256 $binary) -eq $manifest.harness_ex5_sha256
foreach ($name in $publicBinaries.Keys) { $bindingsUnchanged = $bindingsUnchanged -and ((Get-Sha256 (Join-Path $stage $name)) -eq $publicBinaries[$name]) }
$manifest.launch_bindings_unchanged = $bindingsUnchanged
$manifest.passed = $manifest.terminal_started -and $manifest.terminal_exited -and -not $manifest.timed_out -and
    $manifest.terminal_exit_code -eq 0 -and $manifest.cleanup_verified -and $bindingsUnchanged -and
    $parserExit -eq 0 -and $manifest.log_evidence_passed
$manifest.status = $(if ($manifest.passed) { 'FIXTURE_RUNTIME_VERIFIED' } else { 'NOT_VERIFIED' })
$manifest.finished_at_utc = [DateTime]::UtcNow.ToString('o')
Save-Manifest $manifest $manifestPath
Write-Output ('Native math evidence: ' + $manifestPath)
Write-Output ('Status: ' + $manifest.status + '; reason: ' + $manifest.reason)
if (-not $manifest.passed) { exit 1 }
