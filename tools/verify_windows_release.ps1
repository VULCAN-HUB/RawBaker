param([Parameter(Mandatory=$true)][string]$ReleaseDirectory)
$ErrorActionPreference = 'Stop'
$releaseRoot = (Resolve-Path -LiteralPath $ReleaseDirectory).Path
$outputRoot = Join-Path (Split-Path -Parent $releaseRoot) ('RawBaker check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $outputRoot | Out-Null
$report = [ordered]@{ os=[Environment]::OSVersion.VersionString; is64Bit=[Environment]::Is64BitOperatingSystem; verifiedFiles=0; languages=@(); success=$false }
try {
    $manifest = Join-Path $releaseRoot 'SHA256SUMS.txt'
    $hasExecutable = $false
    foreach ($line in Get-Content -LiteralPath $manifest -Encoding UTF8) {
        if ($line -notmatch '^([0-9a-fA-F]{64})  (.+)$') { throw 'Invalid SHA256 manifest entry' }
        $expected = $Matches[1]; $relative = $Matches[2]
        $target = [IO.Path]::GetFullPath((Join-Path $releaseRoot $relative))
        if (-not $target.StartsWith($releaseRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Manifest path outside release' }
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $expected) { throw "Hash mismatch: $relative" }
        if ($relative -eq 'RawBaker.exe') { $hasExecutable = $true }
        $report.verifiedFiles++
    }
    if (-not $hasExecutable) { throw 'Executable missing from manifest' }
    foreach ($language in @('ko','en')) {
        $resultPath = Join-Path $outputRoot ("smoke-$language.json")
        $arguments = @('--smoke-test', ('"' + $resultPath + '"'), '--smoke-language', $language)
        $process = Start-Process -FilePath (Join-Path $releaseRoot 'RawBaker.exe') -ArgumentList $arguments -WindowStyle Hidden -PassThru
        if (-not $process.WaitForExit(180000)) { Stop-Process -Id $process.Id; throw 'Smoke test timed out' }
        $process.Refresh()
        if ($process.ExitCode -ne 0) { throw "Smoke process failed: $language" }
        $result = Get-Content -LiteralPath $resultPath -Encoding UTF8 -Raw | ConvertFrom-Json
        if (-not $result.started -or -not $result.frozen -or $result.language -ne $language -or $result.error) { throw "Startup check failed: $language" }
        $checks = @($result.checks.PSObject.Properties)
        if ($checks.Count -eq 0 -or @($checks | Where-Object { $_.Value -ne $true }).Count -gt 0) { throw "Functional check failed: $language" }
        $report.languages += @{ language=$language; passed=$checks.Count }
    }
    $report.success = $true
} catch {
    $report.error = $_.Exception.Message
} finally {
    $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $outputRoot 'report.json') -Encoding UTF8
    Write-Output $outputRoot
}
if (-not $report.success) { throw $report.error }
