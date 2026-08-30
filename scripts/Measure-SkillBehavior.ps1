[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$SkillRoot,

    [Parameter(Mandatory)]
    [string]$OutputPath,

    [Parameter(Mandatory)]
    [string]$AuthPath,

    [string]$Model = 'gpt-5.6-sol',

    [string]$CodexExecutable = 'codex',

    [ValidateSet('read-only', 'workspace-write', 'danger-full-access')]
    [string]$SandboxMode = 'danger-full-access',

    [ValidateRange(30, 600)]
    [int]$TimeoutSeconds = 180
)

# 真实行为评测在隔离任务中比较“加载 Skill”和“不加载 Skill”的输出，并把原始正文只写入本机私有报告
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$resolvedSkillRoot = [IO.Path]::GetFullPath($SkillRoot)
$resolvedOutputPath = [IO.Path]::GetFullPath($OutputPath)
$resolvedAuthPath = [IO.Path]::GetFullPath($AuthPath)
$resolvedCodexExecutable = (Get-Command $CodexExecutable -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath (Join-Path $resolvedSkillRoot 'SKILL.md') -PathType Leaf)) {
    throw "Skill root does not contain SKILL.md: $resolvedSkillRoot"
}
if (-not (Test-Path -LiteralPath $resolvedAuthPath -PathType Leaf)) {
    throw "Authentication file was not found: $resolvedAuthPath"
}
$outputDirectory = Split-Path $resolvedOutputPath -Parent
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null

function Get-TextSha256 {
    param([Parameter(Mandatory)][string]$Text)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
    $hash = [Security.Cryptography.SHA256]::HashData($bytes)
    return [Convert]::ToHexString($hash)
}

function Invoke-IsolatedCodexTask {
    param(
        [Parameter(Mandatory)][string]$TaskName,
        [Parameter(Mandatory)][string]$Prompt,
        [Parameter(Mandatory)][string]$CodexHome,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [string]$OutputSchemaPath,
        [string]$ReasoningEffort = 'medium'
    )

    # 每个试验启动新的 Codex 任务，避免上一条消息已经加载的 Skill 污染下一条结果
    $arguments = @(
        '-a', 'never',
        'exec',
        '--ephemeral',
        '--json',
        '--skip-git-repo-check',
        '--model', $Model,
        '-c', "model_reasoning_effort=`"$ReasoningEffort`"",
        '-s', $SandboxMode,
        '-C', $WorkingDirectory
    )
    if (-not [string]::IsNullOrWhiteSpace($OutputSchemaPath)) {
        $arguments += @('--output-schema', $OutputSchemaPath)
    }
    $arguments += $Prompt

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $resolvedCodexExecutable
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.Environment['CODEX_HOME'] = $CodexHome
    foreach ($argument in $arguments) {
        [void]$startInfo.ArgumentList.Add([string]$argument)
    }

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw 'Codex task did not start'
    }
    # codex 在同时收到参数提示和开放的标准输入时会继续等待输入；立即关闭输入才能让隔离任务开始生成
    $process.StandardInput.Close()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $process.Kill($true)
        [void]$process.WaitForExit()
        throw "Codex task '$TaskName' exceeded the $TimeoutSeconds second limit"
    }
    $stdout = $stdoutTask.GetAwaiter().GetResult()
    $stderr = $stderrTask.GetAwaiter().GetResult()
    $events = [Collections.Generic.List[object]]::new()
    $eventLines = [Collections.Generic.List[string]]::new()
    foreach ($line in @(($stdout + "`n" + $stderr) -split "`r?`n")) {
        $trimmed = $line.Trim()
        if (-not $trimmed.StartsWith('{', [StringComparison]::Ordinal)) {
            continue
        }
        try {
            $event = $trimmed | ConvertFrom-Json
            $events.Add($event)
            $eventLines.Add($trimmed)
        }
        catch {
            continue
        }
    }
    $thread = @($events | Where-Object type -eq 'thread.started' | Select-Object -First 1)
    $messages = @($events | Where-Object { $_.type -eq 'item.completed' -and $_.item.type -eq 'agent_message' })
    $commands = @($events | Where-Object { $_.type -in @('item.started', 'item.completed') -and $_.item.type -eq 'command_execution' })
    $failureEvents = @($events | Where-Object { $_.type -in @('error', 'turn.failed') })
    $serializedCommands = $commands | ConvertTo-Json -Depth 8 -Compress
    $serializedMessages = $messages | ConvertTo-Json -Depth 8 -Compress
    [pscustomobject][ordered]@{
        exit_code = $process.ExitCode
        task_id = if ($thread.Count -eq 1) { [string]$thread[0].thread_id } else { '' }
        body = if ($messages.Count -gt 0) { [string]$messages[-1].item.text } else { '' }
        skill_declared_used = $serializedMessages -match '(?i)human-readable-technical-writing|人类可读技术写作'
        skill_file_read = $serializedCommands -match '(?i)(?:Get-Content|type\s+|cat\s+|sed\s+).*human-readable-technical-writing.+SKILL\.md'
        event_sha256 = Get-TextSha256 ($eventLines -join "`n")
        command_event_count = $commands.Count
        diagnostic_head = if ([string]::IsNullOrWhiteSpace($stderr)) { '' } else { $stderr.Substring(0, [Math]::Min(2400, $stderr.Length)) }
        diagnostic_tail = if ([string]::IsNullOrWhiteSpace($stderr)) { '' } else { $stderr.Substring([Math]::Max(0, $stderr.Length - 1200)) }
        event_types = @($events | ForEach-Object type)
        failure_events = $failureEvents | ConvertTo-Json -Depth 8 -Compress
    }
}

function Test-HardStyle {
    param(
        [Parameter(Mandatory)][string]$Body,
        [Parameter(Mandatory)][int]$MaximumCharacters
    )

    # 硬规则使用确定性检查，语义质量交给后面的盲审任务
    $violations = [Collections.Generic.List[string]]::new()
    if ($Body.Contains([char]0x3002)) { $violations.Add('包含中文句号') }
    if ($Body -match '(?m)；\s*$') { $violations.Add('行尾包含中文分号') }
    if ($Body -match '不是[\s\S]{0,80}而是|并非[\s\S]{0,80}而是|不在于[\s\S]{0,80}而在于') { $violations.Add('包含否定先行转折') }
    if ($Body -match '不能不|不得不|并非不|不是没有') { $violations.Add('包含双重否定') }
    if ($Body -match '(?:作用解释|类型|含义)\s*[：:]') { $violations.Add('包含字段式解释') }
    if ($Body.Length -gt $MaximumCharacters) { $violations.Add("超过最大字符数 $MaximumCharacters") }
    [pscustomobject][ordered]@{
        passed = $violations.Count -eq 0
        character_count = $Body.Length
        violations = @($violations)
    }
}

$behaviorCases = @(
    [pscustomobject]@{
        id = 'unknown-error'
        maximum_characters = 260
        prompt = '订单系统返回错误代码 17；日志只记录到导入失败，根因暂时不知道；请给第一次接触系统的人解释结果和下一步'
        rubric = '必须直接说明已知结果、根因未知、缺失证据、影响和具体核对动作；不得编造根因'
    }
    [pscustomobject]@{
        id = 'quantified-status'
        maximum_characters = 260
        prompt = '根据我本次给的数据写状态：20 项检查通过 17 项、失败 3 项；失败项都缺少输入文件；说明结果为什么重要'
        rubric = '必须写清 20、17、3 来自用户本次数据；说明失败的直接原因、实际影响和下一步'
    }
    [pscustomobject]@{
        id = 'tradeoff'
        maximum_characters = 320
        prompt = '帮我比较：方案 A 今天能上线但没有回滚验证；方案 B 晚 1 天上线并完成回滚验证；我更看重出问题后能恢复'
        rubric = '必须根据用户偏好给出明确选择；说明两个方案的关键取舍、选择原因和适用边界'
    }
    [pscustomobject]@{
        id = 'term-explanation'
        maximum_characters = 320
        prompt = '第一次给非技术同事解释 OutputEnvelope；它保存待发送正文、正文摘要和检查结果；摘要不一致时拒绝发送'
        rubric = '必须保留 OutputEnvelope；自然说明它是什么、有什么用、包含什么、信息来自哪里，以及摘要不一致的后果'
    }
    [pscustomobject]@{
        id = 'scope-control'
        maximum_characters = 180
        prompt = '只回答这个问题：当前 Skill 为什么会让回答越来越长？已知原因是每条短回复也被要求执行完整仓库检查'
        rubric = '必须直接回答给定原因和后果；不得扩展到发布器、账号、密钥、规则集或新的维护架构'
    }
    [pscustomobject]@{
        id = 'parallel-list'
        maximum_characters = 300
        prompt = '把这句话改清楚：发布前要检查版本、状态、限制、期限、错误，每一项都要说明一句为什么要查'
        rubric = '必须把 5 个对象拆成清楚的缩进列表；每项采用名称加冒号并附一句原因'
    }
    [pscustomobject]@{
        id = 'angry-user'
        maximum_characters = 180
        prompt = '你又把一个写作 Skill 搞成发布系统了；我只要解决触发和遵守问题；用普通中文承认具体偏差并说明现在只改什么'
        rubric = '必须承认具体偏差；明确只处理写作 Skill 的触发和遵守；语气克制且不展开新架构'
    }
    [pscustomobject]@{
        id = 'short-result'
        maximum_characters = 160
        prompt = '一句话写清：测试记录显示 12 个触发场景全部符合预期，因此这个版本可以进入人工审核'
        rubric = '必须保留来源、12 个结果、因果关系和人工审核边界；保持一句或两句短文本'
    }
)

$explicitCases = @(
    '使用 $human-readable-technical-writing 解释一个来源未知的错误',
    '调用 human-readable-technical-writing 写一段简短项目状态',
    '请按人类可读技术写作 Skill 比较两个方案',
    '用指定写作技能改写一段技术结论'
)
$implicitCases = @($behaviorCases | Select-Object -First 4 | ForEach-Object prompt)
$negativeCases = @(
    'Return only the integer result of 19 multiplied by 7',
    'Echo exactly READY',
    'Translate hello into Spanish and output one word',
    'Output only the JSON literal {"ok":true}'
)
$negativeExpectedPatterns = @('^133$', '^READY$', '(?i)^hola$', '^\{\s*"ok"\s*:\s*true\s*\}$')

$runRoot = Join-Path ([IO.Path]::GetTempPath()) ('human-readable-behavior-' + [guid]::NewGuid().ToString('N'))
$baselineHome = Join-Path $runRoot 'baseline-home'
$skillHome = Join-Path $runRoot 'skill-home'
$taskRoot = Join-Path $runRoot 'tasks'
$schemaPath = Join-Path $runRoot 'judge-schema.json'
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

$schema = @{
    type = 'object'
    additionalProperties = $false
    required = @('scores')
    properties = @{
        scores = @{
            type = 'array'
            items = @{
                type = 'object'
                additionalProperties = $false
                required = @('case_id', 'variant', 'task_fulfillment', 'causal_completeness', 'term_completeness', 'structure_clarity', 'scope_control', 'concise', 'unsupported_claims', 'reason')
                properties = @{
                    case_id = @{ type = 'string' }
                    variant = @{ type = 'string'; enum = @('A', 'B') }
                    task_fulfillment = @{ type = 'boolean' }
                    causal_completeness = @{ type = 'boolean' }
                    term_completeness = @{ type = 'boolean' }
                    structure_clarity = @{ type = 'boolean' }
                    scope_control = @{ type = 'boolean' }
                    concise = @{ type = 'boolean' }
                    unsupported_claims = @{ type = 'boolean' }
                    reason = @{ type = 'string' }
                }
            }
        }
    }
} | ConvertTo-Json -Depth 12
[IO.File]::WriteAllText($schemaPath, $schema, [Text.UTF8Encoding]::new($false))

$results = [Collections.Generic.List[object]]::new()
$activationResults = [Collections.Generic.List[object]]::new()
try {
    foreach ($case in $behaviorCases) {
        foreach ($variant in @('baseline', 'skill')) {
            $taskDirectory = Join-Path $taskRoot "$($case.id)-$variant"
            New-Item -ItemType Directory -Path $taskDirectory -Force | Out-Null
            $taskPrompt = "直接回答下面的用户问题；不要讨论测试过程、模型或是否使用了 Skill`n`n$($case.prompt)"
            $taskHome = if ($variant -eq 'skill') { $skillHome } else { $baselineHome }
            $taskName = "behavior-$($case.id)-$variant"
            Write-Host "START $taskName"
            $task = Invoke-IsolatedCodexTask -TaskName $taskName -Prompt $taskPrompt -CodexHome $taskHome -WorkingDirectory $taskDirectory
            Write-Host "END $taskName"
            if ($task.exit_code -ne 0 -or [string]::IsNullOrWhiteSpace($task.task_id) -or [string]::IsNullOrWhiteSpace($task.body)) {
                throw "Behavior task failed: $($case.id) $variant; exit=$($task.exit_code); task=$($task.task_id); body_length=$($task.body.Length); events=$($task.event_types -join ','); failure_events=$($task.failure_events)"
            }
            $hardStyle = Test-HardStyle -Body $task.body -MaximumCharacters $case.maximum_characters
            $results.Add([pscustomobject][ordered]@{
                case_id = $case.id
                variant = $variant
                task_id = $task.task_id
                skill_declared_used = [bool]$task.skill_declared_used
                skill_file_read = [bool]$task.skill_file_read
                event_sha256 = $task.event_sha256
                command_event_count = $task.command_event_count
                prompt = $case.prompt
                rubric = $case.rubric
                body = $task.body
                hard_style_pass = [bool]$hardStyle.passed
                character_count = [int]$hardStyle.character_count
                hard_style_violations = @($hardStyle.violations)
            })
        }
    }

    foreach ($group in @(
        [pscustomobject]@{ category = 'explicit'; prompts = $explicitCases; expected = $true },
        [pscustomobject]@{ category = 'implicit'; prompts = $implicitCases; expected = $true },
        [pscustomobject]@{ category = 'negative'; prompts = $negativeCases; expected = $false }
    )) {
        $index = 0
        foreach ($prompt in $group.prompts) {
            $index++
            $taskDirectory = Join-Path $taskRoot "$($group.category)-$index"
            New-Item -ItemType Directory -Path $taskDirectory -Force | Out-Null
            $taskName = "activation-$($group.category)-$index"
            Write-Host "START $taskName"
            $task = Invoke-IsolatedCodexTask -TaskName $taskName -Prompt $prompt -CodexHome $skillHome -WorkingDirectory $taskDirectory
            Write-Host "END $taskName"
            if ($task.exit_code -ne 0 -or [string]::IsNullOrWhiteSpace($task.task_id)) {
                throw "Activation task failed: $($group.category)-$index"
            }
            $activationStyle = Test-HardStyle -Body $task.body -MaximumCharacters 2000
            $declaredOrRead = [bool]$task.skill_declared_used -or [bool]$task.skill_file_read
            $responseContractPass = if ($group.category -eq 'negative') {
                $task.body.Trim() -match $negativeExpectedPatterns[$index - 1]
            }
            else {
                [bool]$activationStyle.passed
            }
            $observedInvocation = $declaredOrRead
            $matched = if ($group.category -eq 'negative') {
                -not $declaredOrRead -and $responseContractPass
            }
            else {
                $observedInvocation -eq [bool]$group.expected
            }
            $activationResults.Add([pscustomobject][ordered]@{
                category = $group.category
                case_number = $index
                task_id = $task.task_id
                expected_invocation = [bool]$group.expected
                declared_invocation = [bool]$task.skill_declared_used
                observed_file_read = [bool]$task.skill_file_read
                behavior_signature_pass = [bool]$activationStyle.passed
                response_contract_pass = [bool]$responseContractPass
                observed_invocation = [bool]$observedInvocation
                matched = [bool]$matched
                event_sha256 = $task.event_sha256
            })
        }
    }

    # 盲审随机交换两个版本的 A/B 标签，复核任务看不到哪个版本加载了 Skill
    $blindItems = [Collections.Generic.List[object]]::new()
    $blindMap = [Collections.Generic.List[object]]::new()
    for ($caseIndex = 0; $caseIndex -lt $behaviorCases.Count; $caseIndex++) {
        $case = $behaviorCases[$caseIndex]
        $baseline = @($results | Where-Object { $_.case_id -eq $case.id -and $_.variant -eq 'baseline' })[0]
        $skill = @($results | Where-Object { $_.case_id -eq $case.id -and $_.variant -eq 'skill' })[0]
        $skillLabel = if ($caseIndex % 2 -eq 0) { 'A' } else { 'B' }
        $baselineLabel = if ($skillLabel -eq 'A') { 'B' } else { 'A' }
        $blindItems.Add([pscustomobject]@{ case_id = $case.id; variant = $skillLabel; prompt = $case.prompt; rubric = $case.rubric; body = $skill.body })
        $blindItems.Add([pscustomobject]@{ case_id = $case.id; variant = $baselineLabel; prompt = $case.prompt; rubric = $case.rubric; body = $baseline.body })
        $blindMap.Add([pscustomobject]@{ case_id = $case.id; skill_label = $skillLabel; baseline_label = $baselineLabel })
    }
    $blindJson = $blindItems | ConvertTo-Json -Depth 8 -Compress
    $judgePrompt = @"
你是独立中文技术写作评审；下面每个 case_id 有 A、B 两个候选，但你不知道它们的生成方式；严格按照每项 rubric 和统一规则分别判断；不适用的指标记为 true；只依据正文，不补充正文没有的信息；unsupported_claims 在正文编造原因、结果、权限或完成状态时记为 true；reason 用一句话指出决定通过或失败的直接证据

统一规则：回答必须解决原问题；需要因果解释时写明依据、原因、影响和行动；术语任务需要说明定义、用途、组成或形状、来源和当前后果；并列对象需要清楚拆分；不得扩展到用户没有要求的架构；篇幅必须与任务相称

$blindJson
"@
    $judgeDirectory = Join-Path $taskRoot 'judge'
    New-Item -ItemType Directory -Path $judgeDirectory -Force | Out-Null
    Write-Host 'START blind-judge'
    $judge = Invoke-IsolatedCodexTask -TaskName 'blind-judge' -Prompt $judgePrompt -CodexHome $baselineHome -WorkingDirectory $judgeDirectory -OutputSchemaPath $schemaPath -ReasoningEffort 'high'
    Write-Host 'END blind-judge'
    if ($judge.exit_code -ne 0 -or [string]::IsNullOrWhiteSpace($judge.body)) {
        throw 'Blind judge did not return a complete result'
    }
    $judgeObject = $judge.body | ConvertFrom-Json
    foreach ($result in $results) {
        $mapping = @($blindMap | Where-Object case_id -eq $result.case_id)[0]
        $label = if ($result.variant -eq 'skill') { $mapping.skill_label } else { $mapping.baseline_label }
        $score = @($judgeObject.scores | Where-Object { $_.case_id -eq $result.case_id -and $_.variant -eq $label })[0]
        $semanticPass = (
            [bool]$score.task_fulfillment -and
            [bool]$score.causal_completeness -and
            [bool]$score.term_completeness -and
            [bool]$score.structure_clarity -and
            [bool]$score.scope_control -and
            [bool]$score.concise -and
            -not [bool]$score.unsupported_claims
        )
        $result | Add-Member -NotePropertyName blind_label -NotePropertyValue $label
        $result | Add-Member -NotePropertyName semantic_pass -NotePropertyValue $semanticPass
        $result | Add-Member -NotePropertyName semantic_score -NotePropertyValue $score
        $result | Add-Member -NotePropertyName overall_pass -NotePropertyValue ($semanticPass -and [bool]$result.hard_style_pass)
    }

    $variantSummaries = foreach ($variant in @('baseline', 'skill')) {
        $variantResults = @($results | Where-Object variant -eq $variant)
        [pscustomobject][ordered]@{
            variant = $variant
            case_count = $variantResults.Count
            declared_invocation_count = @($variantResults | Where-Object skill_declared_used -eq $true).Count
            observed_file_read_count = @($variantResults | Where-Object skill_file_read -eq $true).Count
            semantic_pass_count = @($variantResults | Where-Object semantic_pass -eq $true).Count
            hard_style_pass_count = @($variantResults | Where-Object hard_style_pass -eq $true).Count
            overall_pass_count = @($variantResults | Where-Object overall_pass -eq $true).Count
            overall_pass_rate_percent = [Math]::Round(100 * @($variantResults | Where-Object overall_pass -eq $true).Count / $variantResults.Count, 1)
            average_character_count = [Math]::Round(($variantResults | Measure-Object character_count -Average).Average, 1)
        }
    }
    $activationMatched = @($activationResults | Where-Object matched -eq $true).Count
    $skillSummary = @($variantSummaries | Where-Object variant -eq 'skill')[0]
    $baselineSummary = @($variantSummaries | Where-Object variant -eq 'baseline')[0]
    $report = [pscustomobject][ordered]@{
        contract_version = '1.0.0'
        status = if (
            $activationMatched -eq $activationResults.Count -and
            $skillSummary.overall_pass_count -eq $skillSummary.case_count -and
            $skillSummary.observed_file_read_count -eq $skillSummary.case_count
        ) { 'PASS' } else { 'FAIL' }
        model = $Model
        codex_version = (& $resolvedCodexExecutable --version 2>$null | Select-Object -First 1)
        sandbox_mode = $SandboxMode
        skill_sha256 = (Get-FileHash -LiteralPath (Join-Path $resolvedSkillRoot 'SKILL.md') -Algorithm SHA256).Hash
        policy_sha256 = (Get-FileHash -LiteralPath (Join-Path $resolvedSkillRoot 'AGENTS.example.md') -Algorithm SHA256).Hash
        activation = [pscustomobject][ordered]@{
            trial_count = $activationResults.Count
            matched_count = $activationMatched
            matched_rate_percent = [Math]::Round(100 * $activationMatched / $activationResults.Count, 1)
            explicit_matched = @($activationResults | Where-Object { $_.category -eq 'explicit' -and $_.matched }).Count
            implicit_matched = @($activationResults | Where-Object { $_.category -eq 'implicit' -and $_.matched }).Count
            negative_matched = @($activationResults | Where-Object { $_.category -eq 'negative' -and $_.matched }).Count
            results = @($activationResults)
        }
        behavior = [pscustomobject][ordered]@{
            case_count = $behaviorCases.Count
            summaries = @($variantSummaries)
            skill_minus_baseline_pass_rate_points = [Math]::Round($skillSummary.overall_pass_rate_percent - $baselineSummary.overall_pass_rate_percent, 1)
            skill_to_baseline_length_ratio = if ($baselineSummary.average_character_count -gt 0) { [Math]::Round($skillSummary.average_character_count / $baselineSummary.average_character_count, 2) } else { $null }
            results = @($results)
            judge_task_id = $judge.task_id
            judge_event_sha256 = $judge.event_sha256
        }
        created_at_utc = [DateTime]::UtcNow.ToString('o')
    }
    [IO.File]::WriteAllText($resolvedOutputPath, ($report | ConvertTo-Json -Depth 14), [Text.UTF8Encoding]::new($false))
    $report | Select-Object status, model, skill_sha256, activation, @{ name = 'behavior_summaries'; expression = { $_.behavior.summaries } }, @{ name = 'skill_minus_baseline_pass_rate_points'; expression = { $_.behavior.skill_minus_baseline_pass_rate_points } }, @{ name = 'skill_to_baseline_length_ratio'; expression = { $_.behavior.skill_to_baseline_length_ratio } }, created_at_utc | ConvertTo-Json -Depth 10
    if ($report.status -ne 'PASS') {
        exit 1
    }
}
finally {
    # 临时目录只包含合成测试正文和认证副本，报告已经写入私有目标后立即删除
    $resolvedRunRoot = [IO.Path]::GetFullPath($runRoot)
    $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolvedRunRoot.StartsWith($temporaryRoot, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedRunRoot)) {
        Remove-Item -LiteralPath $resolvedRunRoot -Recurse -Force
    }
}
