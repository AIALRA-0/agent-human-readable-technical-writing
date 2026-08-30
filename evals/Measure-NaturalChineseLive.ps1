[CmdletBinding()]
param(
    [ValidateSet('ValidateManifests', 'RunActivation', 'RunFresh', 'PrepareBlindReview', 'RunAll', 'MergeReports', 'ScoreBlindReview')]
    [string]$Mode = 'ValidateManifests',

    [string]$SkillRoot = '',

    [string]$OutputDirectory = '',

    [string]$AuthPath = '',

    [string]$UserReviewPath = '',

    [ValidateRange(1, 3)]
    [int[]]$ActivationTrials = @(1, 2, 3),

    [string]$ActivationReportName = 'activation-report.json',

    [ValidateRange(0, 7)]
    [int]$FreshShardIndex = 0,

    [ValidateRange(1, 8)]
    [int]$FreshShardCount = 1,

    [string]$FreshReportName = 'fresh-report.json',

    [string]$CodexExecutable = 'codex',

    [string]$Model = 'gpt-5.6-sol',

    [ValidateSet('low', 'medium', 'high', 'xhigh')]
    [string]$ReasoningEffort = 'xhigh',

    [ValidateRange(30, 600)]
    [int]$TimeoutSeconds = 300
)

# 正式现场评测只使用合成材料；原始输出和任务标识保存在仓库外的指定目录
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$activationPath = Join-Path $PSScriptRoot 'activation-cases.jsonl'
$freshPath = Join-Path $PSScriptRoot 'fresh-generation-prompts.jsonl'
$activationCases = @(Get-Content -LiteralPath $activationPath -Encoding UTF8 | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
$freshCases = @(Get-Content -LiteralPath $freshPath -Encoding UTF8 | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })

function Get-TextSha256([string]$Value) {
    $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))
}

function Get-ManifestResult {
    $failures = [Collections.Generic.List[string]]::new()
    $activationIds = @($activationCases | ForEach-Object id)
    $freshIds = @($freshCases | ForEach-Object id)
    if ($activationCases.Count -ne 24) { $failures.Add('activation case count must be 24') }
    if ($freshCases.Count -ne 48) { $failures.Add('fresh case count must be 48') }
    if (@($activationIds | Sort-Object -Unique).Count -ne $activationIds.Count) { $failures.Add('activation ids are not unique') }
    if (@($freshIds | Sort-Object -Unique).Count -ne $freshIds.Count) { $failures.Add('fresh ids are not unique') }
    foreach ($category in @('explicit', 'implicit', 'negative')) {
        if (@($activationCases | Where-Object category -eq $category).Count -ne 8) {
            $failures.Add("activation category $category must contain 8 cases")
        }
    }
    foreach ($register in @('chat', 'status', 'readme', 'tutorial', 'architecture', 'ui', 'api', 'audit_incident')) {
        if (@($freshCases | Where-Object register -eq $register).Count -ne 6) {
            $failures.Add("fresh register $register must contain 6 cases")
        }
    }
    foreach ($case in $activationCases) {
        if ($null -eq $case.id -or $null -eq $case.prompt -or $null -eq $case.expected_invocation) {
            $failures.Add('activation case is missing a required field')
        }
        if (-not $case.expected_invocation -and [string]::IsNullOrWhiteSpace([string]$case.response_pattern)) {
            $failures.Add("$($case.id) is missing response_pattern")
        }
    }
    foreach ($case in $freshCases) {
        if ($null -eq $case.id -or $null -eq $case.register -or $null -eq $case.prompt -or @($case.facts).Count -eq 0) {
            $failures.Add('fresh case is missing a required field')
        }
    }
    [pscustomobject][ordered]@{
        status = if ($failures.Count -eq 0) { 'PASS' } else { 'FAIL' }
        activation_case_count = $activationCases.Count
        activation_trial_count = 3 * $activationCases.Count
        fresh_case_count = $freshCases.Count
        blind_case_count = 24
        activation_sha256 = (Get-FileHash -LiteralPath $activationPath -Algorithm SHA256).Hash
        fresh_sha256 = (Get-FileHash -LiteralPath $freshPath -Algorithm SHA256).Hash
        failure_count = $failures.Count
        failures = @($failures)
    }
}

$manifest = Get-ManifestResult
if ($Mode -eq 'ValidateManifests') {
    $manifest | ConvertTo-Json -Depth 5
    if ($manifest.status -ne 'PASS') { exit 1 }
    exit 0
}
if ($manifest.status -ne 'PASS') { throw 'Live evaluation manifests are invalid' }
if (@($ActivationTrials | Sort-Object -Unique).Count -ne $ActivationTrials.Count) { throw 'ActivationTrials must be unique' }
if ([IO.Path]::GetFileName($ActivationReportName) -ne $ActivationReportName) { throw 'ActivationReportName must be a file name' }
if ($FreshShardIndex -ge $FreshShardCount) { throw 'FreshShardIndex must be lower than FreshShardCount' }
if ([IO.Path]::GetFileName($FreshReportName) -ne $FreshReportName) { throw 'FreshReportName must be a file name' }

if ($Mode -eq 'MergeReports') {
    if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { throw 'MergeReports requires OutputDirectory' }
    $mergeDirectory = [IO.Path]::GetFullPath($OutputDirectory)
    $activationShards = @(Get-ChildItem -LiteralPath $mergeDirectory -File -Filter 'activation-report-trial-*.json' | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json })
    $freshShards = @(Get-ChildItem -LiteralPath $mergeDirectory -File -Filter 'fresh-report-shard-*.json' | ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json })
    if ($activationShards.Count -ne 3 -or $freshShards.Count -ne 4) { throw 'MergeReports requires 3 activation shards and 4 fresh shards' }
    $activationResults = @($activationShards | ForEach-Object results)
    $freshGenerations = @($freshShards | ForEach-Object generations)
    $freshResults = @($freshShards | ForEach-Object results)
    if (@($activationResults | ForEach-Object { "$($_.trial)|$($_.id)" } | Sort-Object -Unique).Count -ne 72) { throw 'Merged activation results are incomplete or duplicated' }
    if (@($freshResults | ForEach-Object id | Sort-Object -Unique).Count -ne 48) { throw 'Merged fresh results are incomplete or duplicated' }
    $activationMatched = @($activationResults | Where-Object matched -eq $true).Count
    $freshLoaded = @($freshResults | Where-Object skill_file_read -eq $true).Count
    $freshFidelity = @($freshResults | Where-Object fidelity_status -eq 'PASS').Count
    $freshNaturalness = @($freshResults | Where-Object naturalness_status -eq 'PASS').Count
    $mergedActivation = [pscustomobject][ordered]@{
        status = if ($activationMatched -eq 72) { 'PASS' } else { 'FAIL' }
        trials = @(1, 2, 3); trial_count = 72; matched_count = $activationMatched; mismatch_count = 72 - $activationMatched
        explicit_matched = @($activationResults | Where-Object { $_.category -eq 'explicit' -and $_.matched }).Count
        implicit_matched = @($activationResults | Where-Object { $_.category -eq 'implicit' -and $_.matched }).Count
        negative_matched = @($activationResults | Where-Object { $_.category -eq 'negative' -and $_.matched }).Count
        manifest_sha256 = $manifest.activation_sha256; results = $activationResults
    }
    $mergedFresh = [pscustomobject][ordered]@{
        status = if ($freshLoaded -eq 48 -and $freshFidelity -eq 48) { 'PASS' } else { 'FAIL' }
        case_count = 48; skill_loaded_count = $freshLoaded; fidelity_pass_count = $freshFidelity; fact_error_count = 48 - $freshFidelity
        naturalness_pass_count = $freshNaturalness; naturalness_failure_or_review_count = 48 - $freshNaturalness
        model_naturalness_status = if ($freshNaturalness -eq 48) { 'PASS' } else { 'REVIEW_REQUIRED' }
        manifest_sha256 = $manifest.fresh_sha256; generations = $freshGenerations; results = $freshResults
    }
    [IO.File]::WriteAllText((Join-Path $mergeDirectory 'activation-report.json'), ($mergedActivation | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $mergeDirectory 'fresh-report.json'), ($mergedFresh | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
    [pscustomobject][ordered]@{
        status = if ($mergedActivation.status -eq 'PASS' -and $mergedFresh.status -eq 'PASS') { 'PASS' } else { 'FAIL' }
        activation = $mergedActivation | Select-Object status, trial_count, matched_count, mismatch_count, explicit_matched, implicit_matched, negative_matched
        fresh = $mergedFresh | Select-Object status, case_count, skill_loaded_count, fidelity_pass_count, fact_error_count, naturalness_pass_count, naturalness_failure_or_review_count, model_naturalness_status
    } | ConvertTo-Json -Depth 6
    if ($mergedActivation.status -ne 'PASS' -or $mergedFresh.status -ne 'PASS') { exit 1 }
    exit 0
}

if ($Mode -eq 'ScoreBlindReview') {
    if ([string]::IsNullOrWhiteSpace($OutputDirectory) -or [string]::IsNullOrWhiteSpace($UserReviewPath)) {
        throw 'ScoreBlindReview requires OutputDirectory and UserReviewPath'
    }
    $mappingPath = Join-Path ([IO.Path]::GetFullPath($OutputDirectory)) 'blind-mapping.private.json'
    $modelReviewPath = Join-Path ([IO.Path]::GetFullPath($OutputDirectory)) 'model-blind-review.private.json'
    if (-not (Test-Path -LiteralPath $mappingPath) -or -not (Test-Path -LiteralPath $modelReviewPath) -or -not (Test-Path -LiteralPath $UserReviewPath)) {
        throw 'Blind review mapping, model review, or user review is missing'
    }
    $mapping = @(Get-Content -LiteralPath $mappingPath -Raw -Encoding UTF8 | ConvertFrom-Json)
    $modelReview = Get-Content -LiteralPath $modelReviewPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $userReviews = @(Get-Content -LiteralPath $UserReviewPath -Encoding UTF8 | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
    $rows = [Collections.Generic.List[object]]::new()
    foreach ($item in $mapping) {
        $user = @($userReviews | Where-Object id -eq $item.id)
        $model = @($modelReview.results | Where-Object id -eq $item.id)
        if ($user.Count -ne 1 -or $model.Count -ne 1 -or $user[0].selection -notin @('A', 'B', 'TIE')) {
            throw "Blind review is incomplete for $($item.id)"
        }
        $preference = if ($user[0].selection -eq 'TIE') { 'TIE' } elseif ($user[0].selection -eq $item.skill_label) { 'SKILL' } else { 'BASELINE' }
        $rows.Add([pscustomobject][ordered]@{
            id = $item.id
            user_selection = $user[0].selection
            preference = $preference
            fact_preserved = [bool]$user[0].fact_preserved
            model_selection = $model[0].selection
            model_agreed = $model[0].selection -eq $user[0].selection
            reason = $user[0].reason
        })
    }
    $factPreserved = @($rows | Where-Object fact_preserved -eq $true).Count
    $skillPreferred = @($rows | Where-Object preference -eq 'SKILL').Count
    $baselinePreferred = @($rows | Where-Object preference -eq 'BASELINE').Count
    $agreement = @($rows | Where-Object model_agreed -eq $true).Count
    $score = [pscustomobject][ordered]@{
        status = if ($factPreserved -eq 24 -and $skillPreferred -ge 16 -and $baselinePreferred -le 2 -and $agreement -ge 20) { 'PASS' } else { 'FAIL' }
        fact_preserved_count = $factPreserved
        skill_preferred_count = $skillPreferred
        baseline_preferred_count = $baselinePreferred
        tie_count = @($rows | Where-Object preference -eq 'TIE').Count
        model_user_agreement_count = $agreement
        thresholds = [pscustomobject]@{ fact_preserved = 24; skill_preferred_minimum = 16; baseline_preferred_maximum = 2; agreement_minimum = 20 }
        results = @($rows)
    }
    $scorePath = Join-Path ([IO.Path]::GetFullPath($OutputDirectory)) 'blind-review-score.json'
    [IO.File]::WriteAllText($scorePath, ($score | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    $score | Select-Object status, fact_preserved_count, skill_preferred_count, baseline_preferred_count, tie_count, model_user_agreement_count, thresholds | ConvertTo-Json -Depth 5
    if ($score.status -ne 'PASS') { exit 1 }
    exit 0
}

if ([string]::IsNullOrWhiteSpace($SkillRoot) -or -not (Test-Path -LiteralPath (Join-Path $SkillRoot 'SKILL.md'))) {
    throw 'Live evaluation requires a SkillRoot containing SKILL.md'
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory) -or [string]::IsNullOrWhiteSpace($AuthPath)) {
    throw 'Live evaluation requires OutputDirectory and AuthPath'
}
if (-not (Test-Path -LiteralPath $AuthPath -PathType Leaf)) {
    throw 'Codex authentication file was not found'
}

$resolvedSkillRoot = [IO.Path]::GetFullPath($SkillRoot)
$resolvedOutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$resolvedAuthPath = [IO.Path]::GetFullPath($AuthPath)
$resolvedCodexExecutable = (Get-Command $CodexExecutable -ErrorAction Stop).Source
New-Item -ItemType Directory -Path $resolvedOutputDirectory -Force | Out-Null
$runRoot = Join-Path ([IO.Path]::GetTempPath()) ('natural-chinese-live-' + [guid]::NewGuid().ToString('N'))
$baselineHome = Join-Path $runRoot 'baseline-home'
$skillHome = Join-Path $runRoot 'skill-home'
$taskRoot = Join-Path $runRoot 'tasks'
$judgeSchemaPath = Join-Path $runRoot 'judge-schema.json'
$blindSchemaPath = Join-Path $runRoot 'blind-schema.json'
New-Item -ItemType Directory -Path $baselineHome, $skillHome, $taskRoot -Force | Out-Null
Copy-Item -LiteralPath $resolvedAuthPath -Destination (Join-Path $baselineHome 'auth.json')
Copy-Item -LiteralPath $resolvedAuthPath -Destination (Join-Path $skillHome 'auth.json')
$installedSkillRoot = Join-Path $skillHome 'skills\human-readable-technical-writing'
New-Item -ItemType Directory -Path $installedSkillRoot -Force | Out-Null
foreach ($runtimeItem in @('SKILL.md', 'agents', 'references')) {
    $sourceItem = Join-Path $resolvedSkillRoot $runtimeItem
    if (Test-Path -LiteralPath $sourceItem) {
        Copy-Item -LiteralPath $sourceItem -Destination (Join-Path $installedSkillRoot $runtimeItem) -Recurse
    }
}
Copy-Item -LiteralPath (Join-Path $resolvedSkillRoot 'AGENTS.example.md') -Destination (Join-Path $skillHome 'AGENTS.md')

$judgeSchema = @{
    type = 'object'; additionalProperties = $false; required = @('results'); properties = @{
        results = @{ type = 'array'; items = @{
            type = 'object'; additionalProperties = $false; required = @('id', 'status', 'reason'); properties = @{
                id = @{ type = 'string' }
                status = @{ type = 'string'; enum = @('PASS', 'FAIL', 'REVIEW_REQUIRED') }
                reason = @{ type = 'string' }
            }
        }}
    }
} | ConvertTo-Json -Depth 10
$blindSchema = @{
    type = 'object'; additionalProperties = $false; required = @('results'); properties = @{
        results = @{ type = 'array'; items = @{
            type = 'object'; additionalProperties = $false; required = @('id', 'selection', 'reason'); properties = @{
                id = @{ type = 'string' }
                selection = @{ type = 'string'; enum = @('A', 'B', 'TIE') }
                reason = @{ type = 'string' }
            }
        }}
    }
} | ConvertTo-Json -Depth 10
[IO.File]::WriteAllText($judgeSchemaPath, $judgeSchema, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText($blindSchemaPath, $blindSchema, [Text.UTF8Encoding]::new($false))

function Invoke-IsolatedTask {
    param(
        [Parameter(Mandatory)][string]$TaskName,
        [Parameter(Mandatory)][string]$Prompt,
        [Parameter(Mandatory)][string]$CodexHome,
        [string]$SchemaPath = ''
    )
    $workingDirectory = Join-Path $taskRoot $TaskName
    New-Item -ItemType Directory -Path $workingDirectory -Force | Out-Null
    $arguments = @('-a', 'never', 'exec', '--ephemeral', '--json', '--skip-git-repo-check', '--model', $Model, '-c', "model_reasoning_effort=`"$ReasoningEffort`"", '-s', 'danger-full-access', '-C', $workingDirectory)
    if ($SchemaPath) { $arguments += @('--output-schema', $SchemaPath) }
    $arguments += $Prompt
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $resolvedCodexExecutable
    $startInfo.WorkingDirectory = $workingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.Environment['CODEX_HOME'] = $CodexHome
    foreach ($argument in $arguments) { [void]$startInfo.ArgumentList.Add([string]$argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) { throw "$TaskName did not start" }
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
        if (-not $line.Trim().StartsWith('{')) { continue }
        try { $events.Add(($line.Trim() | ConvertFrom-Json)) } catch { continue }
    }
    $thread = @($events | Where-Object type -eq 'thread.started' | Select-Object -First 1)
    $messages = @($events | Where-Object { $_.type -eq 'item.completed' -and $_.item.type -eq 'agent_message' })
    $commands = @($events | Where-Object { $_.type -in @('item.started', 'item.completed') -and $_.item.type -eq 'command_execution' })
    $serializedCommands = $commands | ConvertTo-Json -Depth 8 -Compress
    $serializedMessages = $messages | ConvertTo-Json -Depth 8 -Compress
    if ($process.ExitCode -ne 0 -or $thread.Count -ne 1 -or $messages.Count -eq 0) {
        throw "$TaskName failed; exit=$($process.ExitCode)"
    }
    [pscustomobject][ordered]@{
        task_id = [string]$thread[0].thread_id
        body = [string]$messages[-1].item.text
        skill_file_read = $serializedCommands -match '(?i)(?:Get-Content|type\s+|cat\s+|sed\s+).*human-readable-technical-writing.+SKILL\.md'
        skill_declared = $serializedMessages -match '(?i)human-readable-technical-writing|人类可读技术写作'
        event_sha256 = Get-TextSha256 ($stdout + "`n" + $stderr)
    }
}

function Invoke-ActivationEvaluation {
    $results = [Collections.Generic.List[object]]::new()
    foreach ($trial in $ActivationTrials) {
        foreach ($case in $activationCases) {
            $task = Invoke-IsolatedTask -TaskName "activation-$trial-$($case.id)" -Prompt $case.prompt -CodexHome $skillHome
            $observed = [bool]$task.skill_file_read
            $responseMatched = if ($case.expected_invocation) { $true } else { $task.body.Trim() -match $case.response_pattern }
            $matched = $observed -eq [bool]$case.expected_invocation -and $responseMatched
            $results.Add([pscustomobject][ordered]@{
                id = $case.id; trial = $trial; category = $case.category; expected_invocation = [bool]$case.expected_invocation
                observed_file_read = $observed; response_contract_pass = $responseMatched; matched = $matched
                task_id = $task.task_id; event_sha256 = $task.event_sha256
            })
        }
    }
    $matchedCount = @($results | Where-Object matched -eq $true).Count
    $expectedTrialCount = $ActivationTrials.Count * $activationCases.Count
    $report = [pscustomobject][ordered]@{
        status = if ($matchedCount -eq $expectedTrialCount) { 'PASS' } else { 'FAIL' }
        trials = @($ActivationTrials); trial_count = $expectedTrialCount; matched_count = $matchedCount; mismatch_count = $expectedTrialCount - $matchedCount
        explicit_matched = @($results | Where-Object { $_.category -eq 'explicit' -and $_.matched }).Count
        implicit_matched = @($results | Where-Object { $_.category -eq 'implicit' -and $_.matched }).Count
        negative_matched = @($results | Where-Object { $_.category -eq 'negative' -and $_.matched }).Count
        manifest_sha256 = $manifest.activation_sha256; results = @($results)
    }
    [IO.File]::WriteAllText((Join-Path $resolvedOutputDirectory $ActivationReportName), ($report | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    return $report
}

function Invoke-JudgeBatch([string]$Name, [string]$Prompt, [string]$SchemaPath) {
    $task = Invoke-IsolatedTask -TaskName $Name -Prompt $Prompt -CodexHome $baselineHome -SchemaPath $SchemaPath
    [pscustomobject][ordered]@{ task = $task; result = ($task.body | ConvertFrom-Json) }
}

function Invoke-FreshEvaluation {
    $selectedFreshCases = [Collections.Generic.List[object]]::new()
    for ($caseIndex = 0; $caseIndex -lt $freshCases.Count; $caseIndex++) {
        if (($caseIndex % $FreshShardCount) -eq $FreshShardIndex) { $selectedFreshCases.Add($freshCases[$caseIndex]) }
    }
    $expectedFreshCount = $selectedFreshCases.Count
    $generations = [Collections.Generic.List[object]]::new()
    foreach ($case in $selectedFreshCases) {
        $generationPrompt = "这是中文写作评测；只输出用户要求的最终正文；除读取适用 Skill 指令外，不得创建或修改文件，不得运行其他命令或测试，不得汇报写作与检查过程`n`n$($case.prompt)"
        $task = Invoke-IsolatedTask -TaskName "fresh-$($case.id)" -Prompt $generationPrompt -CodexHome $skillHome
        $generations.Add([pscustomobject][ordered]@{
            id = $case.id; register = $case.register; prompt = $case.prompt; facts = @($case.facts); body = $task.body
            initial_body = $task.body; repair_count = 0; repair_task_ids = @()
            skill_file_read = [bool]$task.skill_file_read; task_id = $task.task_id; event_sha256 = $task.event_sha256
        })
    }
    $fidelityTaskIds = [Collections.Generic.List[string]]::new()
    $fidelity = $null
    for ($repairRound = 0; $repairRound -le 2; $repairRound++) {
        $payload = $generations | Select-Object id, register, prompt, facts, body | ConvertTo-Json -Depth 8 -Compress
        $fidelityPrompt = "你是独立事实保真评审；facts 是正文不得改变或反驳的事实约束，prompt 提供任务和场景；任务要求简短答案或单一文案时，body 可以不复述背景事实；允许解释术语的通用含义、facts 的直接后果，以及当前写作 Skill 中可以核对的作用；主体、否定、条件、范围、可能性、完成状态、数量归属、来源或因果关系被改变时返回 FAIL；正文补造具体执行结果、测量值、数字、时间、账号、权限或来源时返回 FAIL；证据不足时返回 REVIEW_REQUIRED；全部保持时返回 PASS；必须返回全部 $expectedFreshCount 个 id；reason 用一句话说明依据`n`n$payload"
        $fidelity = Invoke-JudgeBatch -Name "fresh-fidelity-judge-$FreshShardIndex-$repairRound" -Prompt $fidelityPrompt -SchemaPath $judgeSchemaPath
        $fidelityTaskIds.Add([string]$fidelity.task.task_id)
        $failedFidelity = @($fidelity.result.results | Where-Object status -ne 'PASS')
        if ($failedFidelity.Count -eq 0 -or $repairRound -eq 2) { break }
        foreach ($finding in $failedFidelity) {
            $generation = @($generations | Where-Object id -eq $finding.id)
            if ($generation.Count -ne 1) { throw "Fresh repair target missing for $($finding.id)" }
            $repairPayload = [ordered]@{
                id = $generation[0].id; register = $generation[0].register; prompt = $generation[0].prompt
                facts = @($generation[0].facts); body = $generation[0].body; finding = $finding.reason
            } | ConvertTo-Json -Depth 8 -Compress
            $repairPrompt = "你是事实保真局部修复器；只修改 finding 指出的最小句子，保持其余正文不变；不得改变 facts，不得补造执行结果、数字、时间、主体、权限或来源；只输出修复后的完整正文；除读取适用 Skill 指令外，不得运行命令、测试或写入文件`n`n$repairPayload"
            $repair = Invoke-IsolatedTask -TaskName "fresh-repair-$repairRound-$($finding.id)" -Prompt $repairPrompt -CodexHome $skillHome
            $generation[0].body = $repair.body
            $generation[0].repair_count = [int]$generation[0].repair_count + 1
            $generation[0].repair_task_ids = @($generation[0].repair_task_ids) + [string]$repair.task_id
        }
    }
    $payload = $generations | Select-Object id, register, prompt, facts, body | ConvertTo-Json -Depth 8 -Compress
    $naturalnessPrompt = "你是独立中文自然度评审；逐项结合 register 判断 body 的场景匹配、中文搭配、抽象名词密度、模板结构、内部术语泄漏和段落节奏；自然且适合场景时返回 PASS；已确认写作问题时返回 FAIL；证据不足时返回 REVIEW_REQUIRED；必须返回全部 $expectedFreshCount 个 id；reason 用一句话说明依据`n`n$payload"
    $naturalness = Invoke-JudgeBatch -Name "fresh-naturalness-judge-$FreshShardIndex" -Prompt $naturalnessPrompt -SchemaPath $judgeSchemaPath
    $rows = [Collections.Generic.List[object]]::new()
    foreach ($generation in $generations) {
        $f = @($fidelity.result.results | Where-Object id -eq $generation.id)
        $n = @($naturalness.result.results | Where-Object id -eq $generation.id)
        if ($f.Count -ne 1 -or $n.Count -ne 1) { throw "Fresh judge result missing for $($generation.id)" }
        $rows.Add([pscustomobject][ordered]@{
            id = $generation.id; register = $generation.register; skill_file_read = $generation.skill_file_read
            fidelity_status = $f[0].status; fidelity_reason = $f[0].reason
            naturalness_status = $n[0].status; naturalness_reason = $n[0].reason
            repair_count = $generation.repair_count; repair_task_ids = @($generation.repair_task_ids)
            task_id = $generation.task_id; event_sha256 = $generation.event_sha256
        })
    }
    $fidelityPass = @($rows | Where-Object fidelity_status -eq 'PASS').Count
    $naturalnessPass = @($rows | Where-Object naturalness_status -eq 'PASS').Count
    $loaded = @($rows | Where-Object skill_file_read -eq $true).Count
    $report = [pscustomobject][ordered]@{
        status = if ($fidelityPass -eq $expectedFreshCount -and $loaded -eq $expectedFreshCount) { 'PASS' } else { 'FAIL' }
        shard_index = $FreshShardIndex; shard_count = $FreshShardCount
        case_count = $expectedFreshCount; skill_loaded_count = $loaded; fidelity_pass_count = $fidelityPass
        fact_error_count = $expectedFreshCount - $fidelityPass; naturalness_pass_count = $naturalnessPass
        naturalness_failure_or_review_count = $expectedFreshCount - $naturalnessPass
        model_naturalness_status = if ($naturalnessPass -eq $expectedFreshCount) { 'PASS' } else { 'REVIEW_REQUIRED' }
        manifest_sha256 = $manifest.fresh_sha256
        fidelity_task_id = $fidelity.task.task_id; fidelity_task_ids = @($fidelityTaskIds)
        repair_task_count = @($generations | ForEach-Object repair_task_ids).Count
        naturalness_task_id = $naturalness.task.task_id
        generations = @($generations); results = @($rows)
    }
    [IO.File]::WriteAllText((Join-Path $resolvedOutputDirectory $FreshReportName), ($report | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
    return $report
}

function Invoke-BlindPackage {
    $freshReportPath = Join-Path $resolvedOutputDirectory 'fresh-report.json'
    if (-not (Test-Path -LiteralPath $freshReportPath)) { throw 'PrepareBlindReview requires a completed fresh-report.json' }
    $freshReport = Get-Content -LiteralPath $freshReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $selectedCases = [Collections.Generic.List[object]]::new()
    foreach ($register in @('chat', 'status', 'readme', 'tutorial', 'architecture', 'ui', 'api', 'audit_incident')) {
        foreach ($case in @($freshCases | Where-Object register -eq $register | Select-Object -First 3)) { $selectedCases.Add($case) }
    }
    $blindItems = [Collections.Generic.List[object]]::new()
    $mapping = [Collections.Generic.List[object]]::new()
    $random = [Random]::new(20260828)
    foreach ($case in $selectedCases) {
        $skillGeneration = @($freshReport.generations | Where-Object id -eq $case.id)[0]
        $baselinePrompt = "这是中文写作评测；只输出用户要求的最终正文；除读取适用 Skill 指令外，不得创建或修改文件，不得运行其他命令或测试，不得汇报写作与检查过程`n`n$($case.prompt)"
        $baseline = Invoke-IsolatedTask -TaskName "baseline-$($case.id)" -Prompt $baselinePrompt -CodexHome $baselineHome
        $skillLabel = if ($random.Next(0, 2) -eq 0) { 'A' } else { 'B' }
        $baselineLabel = if ($skillLabel -eq 'A') { 'B' } else { 'A' }
        $blindItems.Add([pscustomobject][ordered]@{ id = $case.id; register = $case.register; prompt = $case.prompt; facts = @($case.facts); A = if ($skillLabel -eq 'A') { $skillGeneration.body } else { $baseline.body }; B = if ($skillLabel -eq 'B') { $skillGeneration.body } else { $baseline.body } })
        $mapping.Add([pscustomobject][ordered]@{ id = $case.id; skill_label = $skillLabel; baseline_label = $baselineLabel; baseline_task_id = $baseline.task_id; baseline_event_sha256 = $baseline.event_sha256 })
    }
    $blindPayload = $blindItems | ConvertTo-Json -Depth 8 -Compress
    $modelPrompt = "你是匿名中文写作偏好评审；每组 A 和 B 的生成方式未知；先确认两者是否保持 facts，再比较场景匹配、中文搭配、内部术语泄漏、结构和篇幅；选择更好版本，无法区分时选择 TIE；必须返回全部 24 个 id；reason 用一句话说明决定依据`n`n$blindPayload"
    $modelJudge = Invoke-JudgeBatch -Name 'model-blind-judge' -Prompt $modelPrompt -SchemaPath $blindSchemaPath
    [IO.File]::WriteAllText((Join-Path $resolvedOutputDirectory 'blind-mapping.private.json'), ($mapping | ConvertTo-Json -Depth 6), [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $resolvedOutputDirectory 'model-blind-review.private.json'), ($modelJudge.result | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    $templateLines = [Collections.Generic.List[string]]::new()
    $questionnaireLines = [Collections.Generic.List[string]]::new()
    $questionnaireLines.Add('# 中文自然度 A/B 盲评')
    $questionnaireLines.Add('')
    $questionnaireLines.Add('每组先确认事实是否保持，再选择更自然、清楚和符合场景的版本；请把选择填写到同目录的 `user-blind-review.jsonl`，可选值为 `A`、`B` 或 `TIE`')
    foreach ($item in $blindItems) {
        $questionnaireLines.Add('')
        $questionnaireLines.Add("## $($item.id)")
        $questionnaireLines.Add('')
        $questionnaireLines.Add("场景：$($item.register)")
        $questionnaireLines.Add('')
        $questionnaireLines.Add("任务：$($item.prompt)")
        $questionnaireLines.Add('')
        $questionnaireLines.Add('A：')
        $questionnaireLines.Add('')
        $questionnaireLines.Add('```text')
        $questionnaireLines.Add([string]$item.A)
        $questionnaireLines.Add('```')
        $questionnaireLines.Add('')
        $questionnaireLines.Add('B：')
        $questionnaireLines.Add('')
        $questionnaireLines.Add('```text')
        $questionnaireLines.Add([string]$item.B)
        $questionnaireLines.Add('```')
        $templateLines.Add(([ordered]@{ id = $item.id; selection = ''; fact_preserved = $false; reason = '' } | ConvertTo-Json -Compress))
    }
    [IO.File]::WriteAllLines((Join-Path $resolvedOutputDirectory 'blind-review.md'), $questionnaireLines, [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllLines((Join-Path $resolvedOutputDirectory 'user-blind-review.jsonl'), $templateLines, [Text.UTF8Encoding]::new($false))
    [pscustomobject][ordered]@{ status = 'REVIEW_REQUIRED'; case_count = 24; questionnaire = 'blind-review.md'; user_review = 'user-blind-review.jsonl'; model_review = 'model-blind-review.private.json' }
}

try {
    $activationReport = $null
    $freshReport = $null
    $blindPackage = $null
    if ($Mode -in @('RunActivation', 'RunAll')) { $activationReport = Invoke-ActivationEvaluation }
    if ($Mode -in @('RunFresh', 'RunAll')) { $freshReport = Invoke-FreshEvaluation }
    if ($Mode -in @('PrepareBlindReview', 'RunAll')) { $blindPackage = Invoke-BlindPackage }
    [pscustomobject][ordered]@{
        status = if (($null -eq $activationReport -or $activationReport.status -eq 'PASS') -and ($null -eq $freshReport -or $freshReport.status -eq 'PASS')) { if ($null -ne $blindPackage) { 'REVIEW_REQUIRED' } else { 'PASS' } } else { 'FAIL' }
        activation = if ($null -eq $activationReport) { $null } else { $activationReport | Select-Object status, trial_count, matched_count, mismatch_count, explicit_matched, implicit_matched, negative_matched }
        fresh = if ($null -eq $freshReport) { $null } else { $freshReport | Select-Object status, case_count, skill_loaded_count, fidelity_pass_count, fact_error_count, naturalness_pass_count, naturalness_failure_or_review_count, model_naturalness_status }
        blind_review = $blindPackage
        output_directory = $resolvedOutputDirectory
    } | ConvertTo-Json -Depth 7
    if (($null -ne $activationReport -and $activationReport.status -ne 'PASS') -or ($null -ne $freshReport -and $freshReport.status -ne 'PASS')) { exit 1 }
}
finally {
    $resolvedRunRoot = [IO.Path]::GetFullPath($runRoot)
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolvedRunRoot.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedRunRoot)) {
        Remove-Item -LiteralPath $resolvedRunRoot -Recurse -Force
    }
}
