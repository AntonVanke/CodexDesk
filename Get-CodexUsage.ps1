param(
    [switch]$Json,
    [string]$CodexPath
)

$ErrorActionPreference = 'Stop'

if (-not $CodexPath) {
    $command = Get-Command codex -ErrorAction SilentlyContinue
    if (-not $command) {
        $desktop = Get-AppxPackage OpenAI.Codex | Select-Object -First 1
        $CodexPath = Join-Path $desktop.InstallLocation 'app\resources\codex.exe'
    } elseif ($command.Source -like '*.exe') {
        $CodexPath = $command.Source
    } else {
        $package = Join-Path (Split-Path $command.Source) 'node_modules\@openai\codex'
        $CodexPath = Get-ChildItem -LiteralPath $package -Filter codex.exe -File -Recurse |
            Select-Object -First 1 -ExpandProperty FullName
    }
}
if (-not $CodexPath) { throw 'Codex executable not found. Supply -CodexPath.' }

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $CodexPath
$startInfo.Arguments = 'app-server --listen stdio://'
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.RedirectStandardInput = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $startInfo

function Send-Rpc($Message) {
    $process.StandardInput.WriteLine(($Message | ConvertTo-Json -Depth 10 -Compress))
    $process.StandardInput.Flush()
}

function Read-RpcResponse([int]$Id) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 30) {
        $read = $process.StandardOutput.ReadLineAsync()
        $remainingMs = [Math]::Max(1, [int](30000 - $timer.Elapsed.TotalMilliseconds))
        if (-not $read.Wait($remainingMs)) { throw 'Codex usage request timed out.' }
        if ($null -eq $read.Result) { throw 'Codex app-server exited before replying.' }
        $message = $read.Result | ConvertFrom-Json
        if ($null -ne $message.id -and $message.id -eq $Id) {
            if ($message.error) { throw $message.error.message }
            return $message.result
        }
    }
    throw 'Codex usage request timed out.'
}

try {
    [void]$process.Start()
    $stderrDrain = $process.StandardError.ReadToEndAsync()
    Send-Rpc @{ id = 1; method = 'initialize'; params = @{
        clientInfo = @{ name = 'local_usage_reader'; version = '1.0.0' }
    } }
    $null = Read-RpcResponse 1
    Send-Rpc @{ method = 'initialized'; params = @{} }
    Send-Rpc @{ id = 2; method = 'account/rateLimits/read' }
    $result = Read-RpcResponse 2
} finally {
    if ($process.Id -and -not $process.HasExited) {
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(2000)) { $process.Kill() }
    }
    $process.Dispose()
}

$buckets = if ($result.rateLimitsByLimitId) {
    @($result.rateLimitsByLimitId.PSObject.Properties | ForEach-Object { $_.Value })
} else {
    @($result.rateLimits)
}
$beijing = [TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$windows = @(foreach ($bucket in $buckets) {
    foreach ($slot in @('primary', 'secondary')) {
        $window = $bucket.$slot
        if ($null -eq $window) { continue }
        $reset = if ($null -ne $window.resetsAt) {
            [TimeZoneInfo]::ConvertTime(
                [DateTimeOffset]::FromUnixTimeSeconds([long]$window.resetsAt), $beijing
            ).ToString('yyyy-MM-dd HH:mm:ss zzz')
        } else { $null }
        $remaining = if ($null -ne $window.usedPercent) {
            [Math]::Max(0, [Math]::Min(100, 100 - $window.usedPercent))
        } else { $null }
        [pscustomobject]@{
            limitId = $bucket.limitId
            plan = $bucket.planType
            window = $slot
            windowDurationMins = $window.windowDurationMins
            usedPercent = $window.usedPercent
            remainingPercent = $remaining
            resetsAt = $window.resetsAt
            resetBeijing = $reset
        }
    }
})
if ($windows.Count -eq 0) {
    throw 'No quota windows returned. Check ChatGPT login with: codex login status'
}
if ($Json) {
    [pscustomobject]@{
        checkedAtUtc = [DateTimeOffset]::UtcNow.ToString('o')
        windows = $windows
        availableResets = $result.rateLimitResetCredits.availableCount
    } | ConvertTo-Json -Depth 8
} else {
    $windows | Format-Table limitId, plan, windowDurationMins, remainingPercent, resetBeijing -AutoSize
}
