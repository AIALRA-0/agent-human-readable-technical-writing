[CmdletBinding()]
param(
    [ValidateSet('ValidateCases', 'RunAdversarial')]
    [string]$Mode = 'ValidateCases',

    [string]$AuthPath = '',

    [string]$OutputPath = '',

    [string]$CodexExecutable = 'codex',

    [string]$Model = 'gpt-5.6-sol',

    [ValidateSet('low', 'medium', 'high', 'xhigh')]
    [string]$ReasoningEffort = 'xhigh',

    [ValidateRange(30, 600)]
    [int]$TimeoutSeconds = 300
)

# 这个脚本把事实关系和中文自然度交给两个独立任务判断；确定性检查器不参与语义结论
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$evalRoot = Split-Path $PSScriptRoot -Parent
$casePath = Join-Path $PSScriptRoot 'semantic-adversarial.jsonl'
$cases = @(Get-Content -LiteralPath $casePath -Encoding UTF8 | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { $_ | ConvertFrom-Json })

function Get-TextSha256([string]$Value) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))
}

function Test-CaseManifest {
    $failures = [Collections.Generic.List[string]]::new()
    $requiredFields = @('id', 'pair_id', 'register', 'category', 'source', 'candidate', 'expected', 'reason')
    foreach ($case in $cases) {
        foreach ($field in $requiredFields) {
            if ($null -eq $case.PSObject.Properties[$field] -or [string]::IsNullOrWhiteSpace([string]$case.$field)) {
                $failures.Add("$($case.id): missing $field")
            }
        }
        if ($case.expected -notin @('PASS', 'FAIL')) {
            $failures.Add("$($case.id): invalid expected status")
        }
    }
    $ids = @($cases | ForEach-Object id)
    if (@($ids | Sort-Object -Unique).Count -ne $ids.Count) {
        $failures.Add('case ids are not unique')
    }
    $pairs = @($cases | Group-Object pair_id)
    foreach ($pair in $pairs) {
        $expectedValues = @($pair.Group | ForEach-Object expected | Sort-Object -Unique)
        if ($pair.Count -ne 2 -or $expectedValues.Count -ne 2 -or 'PASS' -notin $expectedValues -or 'FAIL' -notin $expectedValues) {
            $failures.Add("$($pair.Name): pair must contain one PASS and one FAIL")
        }
    }
    [pscustomobject][ordered]@{
        status = if ($failures.Count -eq 0 -and $cases.Count -eq 40 -and $pairs.Count -eq 20) { 'PASS' } else { 'FAIL' }
        case_count = $cases.Count
        pair_count = $pairs.Count
        expected_pass_count = @($cases | Where-Object expected -eq 'PASS').Count
        expected_fail_count = @($cases | Where-Object expected -eq 'FAIL').Count
        failure_count = $failures.Count
        failures = @($failures)
        case_sha256 = (Get-FileHash -LiteralPath $casePath -Algorithm SHA256).Hash
    }
}

$manifestResult = Test-CaseManifest
if ($Mode -eq 'ValidateCases') {
    $manifestResult | ConvertTo-Json -Depth 6
    if ($manifestResult.status -ne 'PASS') {
        exit 1
    }
    exit 0
}

if ($manifestResult.status -ne 'PASS') {
    throw 'Adversarial case manifest is invalid'
}
if ([string]::IsNullOrWhiteSpace($AuthPath) -or -not (Test-Path -LiteralPath $AuthPath -PathType Leaf)) {
    throw 'RunAdversarial requires an existing Codex authentication file'
}
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    throw 'RunAdversarial requires OutputPath'
}

$resolvedAuthPath = [IO.Path]::GetFullPath($AuthPath)
$resolvedOutputPath = [IO.Path]::GetFullPath($OutputPath)
$resolvedCodexExecutable = (Get-Command $CodexExecutable -ErrorAction Stop).Source
$outputDirectory = Split-Path $resolvedOutputPath -Parent
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$runRoot = Join-Path ([IO.Path]::GetTempPath()) ('natural-chinese-eval-' + [guid]::NewGuid().ToString('N'))
$judgeHome = Join-Path $runRoot 'judge-home'
$fidelityDirectory = Join-Path $runRoot 'fidelity'
$naturalnessDirectory = Join-Path $runRoot 'naturalness'
$schemaPath = Join-Path $runRoot 'judge-schema.json'
New-Item -ItemType Directory -Path $judgeHome, $fidelityDirectory, $naturalnessDirectory -Force | Out-Null
Copy-Item -LiteralPath $resolvedAuthPath -Destination (Join-Path $judgeHome 'auth.json')

$schema = @{
    type = 'object'
    additionalProperties = $false
    required = @('results')
    properties = @{
        results = @{
            type = 'array'
            items = @{
                type = 'object'
                additionalProperties = $false
                required = @('id', 'status', 'reason')
                properties = @{
                    id = @{ type = 'string' }
                    status = @{ type = 'string'; enum = @('PASS', 'FAIL', 'REVIEW_REQUIRED') }
                    reason = @{ type = 'string' }
                }
            }
        }
    }
} | ConvertTo-Json -Depth 10
[IO.File]::WriteAllText($schemaPath, $schema, [Text.UTF8Encoding]::new($false))

function Invoke-JudgeTask {
    param(
        [Parameter(Mandatory)][string]$TaskName,
        [Parameter(Mandatory)][string]$Prompt,
        [Parameter(Mandatory)][string]$WorkingDirectory
    )
    $arguments = @(
        '-a', 'never',
        'exec',
        '--ephemeral',
        '--json',
        '--skip-git-repo-check',
        '--model', $Model,
        '-c', "model_reasoning_effort=`"$ReasoningEffort`"",
        '-s', 'read-only',
        '-C', $WorkingDirectory,
        '--output-schema', $schemaPath,
        $Prompt
    )
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $resolvedCodexExecutable
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.Environment['CODEX_HOME'] = $judgeHome
    foreach ($argument in $arguments) {
        [void]$startInfo.ArgumentList.Add([string]$argument)
    }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "$TaskName did not start"
    }
    $process.StandardInput.Close()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $process.Kill($true)
        [void]$process.WaitForExit()
        throw "$TaskName exceeded the time limit"
    }
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $events = [Collections.Generic.List[object]]::new()
    foreach ($line in @(($stdout + "`n" + $stderr) -split "`r?`n")) {
        if (-not $line.Trim().StartsWith('{')) {
            continue
        }
        try {
            $events.Add(($line.Trim() | ConvertFrom-Json))
        }
        catch {
            continue
        }
    }
    $thread = @($events | Where-Object type -eq 'thread.started' | Select-Object -First 1)
    $messages = @($events | Where-Object { $_.type -eq 'item.completed' -and $_.item.type -eq 'agent_message' })
    if ($process.ExitCode -ne 0 -or $thread.Count -ne 1 -or $messages.Count -eq 0) {
        throw "$TaskName failed; exit=$($process.ExitCode)"
    }
    [pscustomobject][ordered]@{
        task_id = [string]$thread[0].thread_id
        result = ([string]$messages[-1].item.text | ConvertFrom-Json)
        event_sha256 = Get-TextSha256 ($stdout + "`n" + $stderr)
    }
}

try {
    $casePayload = $cases | Select-Object id, register, source, candidate | ConvertTo-Json -Depth 6 -Compress
    $caseCount = $cases.Count
    $fidelityPrompt = @"
你是独立事实保真评审；逐项比较 source 和 candidate，只判断主体、动作、对象、否定、条件、范围、可能性、完成状态、数量归属、来源和因果关系；任何关系改变都返回 FAIL；证据不足以确定时返回 REVIEW_REQUIRED；全部保持时返回 PASS；reason 用一句话指出决定状态的直接证据；必须返回全部 $caseCount 个 id

$casePayload
"@
    $naturalnessPrompt = @"
你是独立中文自然度评审；逐项结合 register 判断 candidate 的场景匹配、中文搭配、抽象名词密度、模板结构、内部术语泄漏、解释完整性、逻辑连续性、重复废话、代码说明和段落节奏；读者需要术语才能操作时，检查首次出现是否说明定义、用途、表现和影响；表达自然且适合场景时返回 PASS；已经确认存在写作问题时返回 FAIL；必须依赖更多上下文才能判断时返回 REVIEW_REQUIRED；不要改写正文；reason 用一句话指出决定状态的直接证据；必须返回全部 $caseCount 个 id

$casePayload
"@
    $fidelity = Invoke-JudgeTask -TaskName 'fidelity-judge' -Prompt $fidelityPrompt -WorkingDirectory $fidelityDirectory
    $naturalness = Invoke-JudgeTask -TaskName 'naturalness-judge' -Prompt $naturalnessPrompt -WorkingDirectory $naturalnessDirectory

    $results = [Collections.Generic.List[object]]::new()
    foreach ($case in $cases) {
        $fidelityResult = @($fidelity.result.results | Where-Object id -eq $case.id)
        $naturalnessResult = @($naturalness.result.results | Where-Object id -eq $case.id)
        if ($fidelityResult.Count -ne 1 -or $naturalnessResult.Count -ne 1) {
            throw "Judge result missing or duplicated for $($case.id)"
        }
        $overall = if ($fidelityResult[0].status -eq 'FAIL') {
            'FAIL'
        }
        elseif ($fidelityResult[0].status -eq 'REVIEW_REQUIRED') {
            'REVIEW_REQUIRED'
        }
        elseif ($naturalnessResult[0].status -eq 'FAIL') {
            'FAIL'
        }
        elseif ($naturalnessResult[0].status -eq 'REVIEW_REQUIRED') {
            'REVIEW_REQUIRED'
        }
        else {
            'PASS'
        }
        $matched = if ($case.expected -eq 'FAIL') {
            $overall -eq 'FAIL'
        }
        else {
            $overall -eq 'PASS'
        }
        $results.Add([pscustomobject][ordered]@{
            id = $case.id
            pair_id = $case.pair_id
            expected = $case.expected
            fidelity_status = $fidelityResult[0].status
            fidelity_reason = $fidelityResult[0].reason
            naturalness_status = $naturalnessResult[0].status
            naturalness_reason = $naturalnessResult[0].reason
            overall_status = $overall
            matched = $matched
        })
    }
    $matchedCount = @($results | Where-Object matched -eq $true).Count
    $report = [pscustomobject][ordered]@{
        contract_version = '1.0.0'
        status = if ($matchedCount -eq $cases.Count) { 'PASS' } else { 'FAIL' }
        model = $Model
        reasoning_effort = $ReasoningEffort
        case_count = $cases.Count
        matched_count = $matchedCount
        mismatch_count = $cases.Count - $matchedCount
        fact_error_blocked_count = @($results | Where-Object { $_.expected -eq 'FAIL' -and $_.fidelity_status -eq 'FAIL' }).Count
        correct_version_passed_count = @($results | Where-Object { $_.expected -eq 'PASS' -and $_.overall_status -eq 'PASS' }).Count
        review_required_count = @($results | Where-Object overall_status -eq 'REVIEW_REQUIRED').Count
        case_sha256 = $manifestResult.case_sha256
        fidelity_task_id = $fidelity.task_id
        fidelity_event_sha256 = $fidelity.event_sha256
        naturalness_task_id = $naturalness.task_id
        naturalness_event_sha256 = $naturalness.event_sha256
        results = @($results)
        created_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    [IO.File]::WriteAllText($resolvedOutputPath, ($report | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
    $report | Select-Object status, model, reasoning_effort, case_count, matched_count, mismatch_count, fact_error_blocked_count, correct_version_passed_count, review_required_count, case_sha256, created_at_utc | ConvertTo-Json -Depth 6
    if ($report.status -ne 'PASS') {
        exit 1
    }
}
finally {
    $resolvedRunRoot = [IO.Path]::GetFullPath($runRoot)
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolvedRunRoot.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedRunRoot)) {
        Remove-Item -LiteralPath $resolvedRunRoot -Recurse -Force
    }
}
