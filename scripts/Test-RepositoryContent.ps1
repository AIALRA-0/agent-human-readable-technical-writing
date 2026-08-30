[CmdletBinding()]
param()

# 启用严格检查，让仓库自查在变量或路径错误时立即失败
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 根据脚本位置确定仓库根目录，保证本地和自动检查环境使用同一组文件
$skillRoot = Split-Path $PSScriptRoot -Parent
$linter = Join-Path $PSScriptRoot 'Test-HumanReadableChinese.ps1'
$exporter = Join-Path $PSScriptRoot 'Export-QualityCases.ps1'
$qualityCases = Join-Path $skillRoot 'QA-CASES.md'
$readme = Join-Path $skillRoot 'README.md'
$skillDefinition = Join-Path $skillRoot 'SKILL.md'
$ruleTests = Join-Path $PSScriptRoot 'Test-HumanReadableChinese.Tests.ps1'

# 检查仓库中的全部 Markdown 文档，新增文档也会自动进入检查范围
$documentResults = [Collections.Generic.List[object]]::new()
$markdownFiles = @(Get-ChildItem -LiteralPath $skillRoot -Recurse -File -Filter '*.md')
foreach ($file in $markdownFiles) {
    # 英文版文档继续参加链接和文件完整性检查，不进入只面向中文正文的写作检查器
    if ($file.Name -match '\.en\.md$') {
        $documentResults.Add([pscustomobject]@{
            path = [IO.Path]::GetRelativePath($skillRoot, $file.FullName)
            status = 'PASS'
            issue_count = 0
            rules = @()
            warning_count = 0
            warnings = @()
        })
        continue
    }
    # 完整案例文档属于问答页面，正式评估仍会逐个限制普通案例中的疑问句标题
    $lintArguments = @{
        Path = $file.FullName
    }
    if ($file.FullName -eq $qualityCases) {
        $lintArguments.AllowQuestionHeadings = $true
        # 汇总文档同时包含默认题注和用户明确指定的出版题注；每个原始案例已经使用自己的题注配置通过检查
        $lintArguments.AllowMixedTableCaptionPositions = $true
    }
    $lintResult = (& $linter @lintArguments | Out-String) | ConvertFrom-Json
    $documentResults.Add([pscustomobject]@{
        path = [IO.Path]::GetRelativePath($skillRoot, $file.FullName)
        status = $lintResult.status
        issue_count = $lintResult.issue_count
        rules = @($lintResult.issues | ForEach-Object { $_.rule })
        warning_count = $lintResult.warning_count
        warnings = @($lintResult.warnings | ForEach-Object { $_.rule })
    })
}

# 解析仓库中的全部 PowerShell 脚本，避免自查只覆盖说明文字而忽略执行文件
$scriptParseErrors = [Collections.Generic.List[object]]::new()
$powerShellFiles = @(Get-ChildItem -LiteralPath $skillRoot -Recurse -File -Filter '*.ps1')
foreach ($file in $powerShellFiles) {
    $tokens = $null
    $errors = $null
    [Management.Automation.Language.Parser]::ParseFile(
        $file.FullName,
        [ref]$tokens,
        [ref]$errors
    ) | Out-Null
    foreach ($error in $errors) {
        $scriptParseErrors.Add([pscustomobject]@{
            path = [IO.Path]::GetRelativePath($skillRoot, $file.FullName)
            line = $error.Extent.StartLineNumber
            message = $error.Message
        })
    }
}

# 重新导出案例到临时文件，确认公开案例没有落后于正式质量测试
$temporaryCases = Join-Path ([IO.Path]::GetTempPath()) ("human-readable-qa-" + [guid]::NewGuid().ToString('N') + '.md')
try {
    & $exporter -OutputPath $temporaryCases | Out-Null
    $committedCasesText = Get-Content -LiteralPath $qualityCases -Raw -Encoding UTF8
    $generatedCasesText = Get-Content -LiteralPath $temporaryCases -Raw -Encoding UTF8
    $qualityCasesCurrent = $committedCasesText -ceq $generatedCasesText
}
finally {
    if (Test-Path -LiteralPath $temporaryCases) {
        Remove-Item -LiteralPath $temporaryCases -Force
    }
}

# 比较自动统计和仓库首页徽章，避免测试数量增加后首页继续显示旧数字
$ruleTestText = Get-Content -LiteralPath $ruleTests -Raw -Encoding UTF8
$ruleCaseCount = [regex]::Matches($ruleTestText, '(?m)^\s*Name\s*=').Count
$qualityCasesText = Get-Content -LiteralPath $qualityCases -Raw -Encoding UTF8
$qualityCaseMatch = [regex]::Match($qualityCasesText, '(?m)^- 全部案例数量：(?<count>\d+)\r?$')
$qualityCaseCount = if ($qualityCaseMatch.Success) {
    [int]$qualityCaseMatch.Groups['count'].Value
}
else {
    0
}
$readmeText = Get-Content -LiteralPath $readme -Raw -Encoding UTF8
$readmeStatisticsCurrent = (
    $readmeText -match "rule_checks-$ruleCaseCount-" -and
    $readmeText -match "full_QA_cases-$qualityCaseCount-"
)

# 核心技能只保留运行规则和资源路由，复杂报告与开发测试通过独立参考文件按需加载
$skillText = Get-Content -LiteralPath $skillDefinition -Raw -Encoding UTF8
$skillLineCount = @(Get-Content -LiteralPath $skillDefinition -Encoding UTF8).Count
$requiredProgressiveReferences = @(
    'references/natural-chinese.md'
    'references/structured-documents.md'
    'references/technical-content.md'
    'references/complex-reports.md'
    'references/style-rules.md'
    'references/quality-development.md'
)
$missingProgressiveReferences = @(
    $requiredProgressiveReferences |
        Where-Object {
            -not (Test-Path -LiteralPath (Join-Path $skillRoot $_) -PathType Leaf) -or
            $skillText -notmatch [regex]::Escape($_)
        }
)
$progressiveLoadingValid = (
    $skillLineCount -le 120 -and
    $missingProgressiveReferences.Count -eq 0 -and
    $skillText -match '普通回答不得加载质量测试说明' -and
    $skillText -notmatch '质量测试至少包含二十四组'
)
$linterText = Get-Content -LiteralPath $linter -Raw -Encoding UTF8

# 自然化开发文件必须保持单一场景参考、平衡最小对照和独立语义评估入口
$naturalChineseReference = Join-Path $skillRoot 'references\natural-chinese.md'
$semanticCases = Join-Path $skillRoot 'evals\semantic-adversarial.jsonl'
$minimalPairs = Join-Path $skillRoot 'evals\minimal-pairs.jsonl'
$preferences = Join-Path $skillRoot 'evals\user-preferences.jsonl'
$naturalEvaluation = Join-Path $skillRoot 'evals\Invoke-NaturalChineseEvaluation.ps1'
$liveEvaluation = Join-Path $skillRoot 'evals\Measure-NaturalChineseLive.ps1'
$activationCases = Join-Path $skillRoot 'evals\activation-cases.jsonl'
$freshCases = Join-Path $skillRoot 'evals\fresh-generation-prompts.jsonl'
$semanticCaseCount = if (Test-Path -LiteralPath $semanticCases) { @(Get-Content -LiteralPath $semanticCases | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count } else { 0 }
$minimalPairCount = if (Test-Path -LiteralPath $minimalPairs) { @(Get-Content -LiteralPath $minimalPairs | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count } else { 0 }
$preferenceCount = if (Test-Path -LiteralPath $preferences) { @(Get-Content -LiteralPath $preferences | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count } else { 0 }
$activationCaseCount = if (Test-Path -LiteralPath $activationCases) { @(Get-Content -LiteralPath $activationCases | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count } else { 0 }
$freshCaseCount = if (Test-Path -LiteralPath $freshCases) { @(Get-Content -LiteralPath $freshCases | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count } else { 0 }
$naturalChineseModelValid = (
    (Test-Path -LiteralPath $naturalChineseReference -PathType Leaf) -and
    (Test-Path -LiteralPath $naturalEvaluation -PathType Leaf) -and
    (Test-Path -LiteralPath $liveEvaluation -PathType Leaf) -and
    $semanticCaseCount -eq 40 -and
    $minimalPairCount -eq 72 -and
    $preferenceCount -eq 33 -and
    $activationCaseCount -eq 24 -and
    $freshCaseCount -eq 48 -and
    $skillText -match '事实与关系' -and
    $skillText -match 'references/natural-chinese.md' -and
    $skillText -match '标题可以使用“和、与、及、顿号”' -and
    $linterText -match 'PROTECTED_TOKEN_MISSING' -and
    $linterText -notmatch "title -match '\(\?:和\|与\|及\|、\)'"
)

# 核心规则、复杂报告规则和自动检查器必须同时保留编辑过程元叙述门禁
$complexReportText = Get-Content -LiteralPath (Join-Path $skillRoot 'references\complex-reports.md') -Raw -Encoding UTF8
$editorialProcessGateValid = (
    $skillText -match '编辑过程元叙述' -and
    $complexReportText -match '编辑过程边界' -and
    $linterText -match 'EDITORIAL_PROCESS_META_NARRATIVE_FORBIDDEN' -and
    $linterText -match 'AllowEditorialProcessNarrative'
)

# 段落级主体、列表步骤和英文术语提醒需要分别进入核心规则、按需参考和检查器
$structuredText = Get-Content -LiteralPath (Join-Path $skillRoot 'references\structured-documents.md') -Raw -Encoding UTF8
$technicalText = Get-Content -LiteralPath (Join-Path $skillRoot 'references\technical-content.md') -Raw -Encoding UTF8
$paragraphAndWarningModelValid = (
    $skillText -match '段落层面完整' -and
    $skillText -match '相邻句子必须增加' -and
    $structuredText -match '第一步，安装依赖' -and
    $structuredText -match '第一步：核对以下内容' -and
    $technicalText -match '一份连续文档只在术语首次出现时完整解释一次' -and
    $linterText -match 'PROCEDURAL_STEPS_REQUIRE_LIST' -and
    $linterText -match 'LOW_INFORMATION_LEAD_SHOULD_BE_REMOVED' -and
    $linterText -match 'warning_count' -and
    $linterText -match 'seenInDocument'
)

# 阿拉伯数字偏好和原生名称保留必须同时进入核心规则、技术参考和自动检查
$numericAndNativeNameModelValid = (
    $skillText -match '精确数量、测量值、日期、时长、金额、百分比和阈值优先使用阿拉伯数字' -and
    $skillText -match '不编造生硬音译' -and
    $technicalText -match '四百二十六个.*426个' -and
    $technicalText -match '行业惯例和原始名称的可检索性高于逐词翻译' -and
    $linterText -match 'EXACT_QUANTITY_SHOULD_USE_ARABIC_DIGITS' -and
    $linterText -match 'RELATIONAL_NUMBERS_REQUIRE_CALCULATION' -and
    $linterText -match 'AGGREGATE_COUNT_REQUIRES_DERIVATION' -and
    $linterText -match 'Test-HasNaturalEnglishExplanation'
)

# 核对全部相对文档链接，避免仓库页面指向不存在的本地文件
$missingLinks = [Collections.Generic.List[string]]::new()
foreach ($file in $markdownFiles) {
    $text = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8
    $linkMatches = [regex]::Matches($text, '(?<!\!)\[[^\]]+\]\((?<target>[^)]+)\)')
    foreach ($linkMatch in $linkMatches) {
        $target = $linkMatch.Groups['target'].Value.Trim()
        if ($target -match '^(?:https?://|mailto:|#)' -or $target -match '^<https?://') {
            continue
        }
        $pathPart = ($target -split '#', 2)[0].Trim('<>')
        if ([string]::IsNullOrWhiteSpace($pathPart)) {
            continue
        }
        $resolvedTarget = Join-Path $file.DirectoryName $pathPart
        if (-not (Test-Path -LiteralPath $resolvedTarget)) {
            $missingLinks.Add("$([IO.Path]::GetRelativePath($skillRoot, $file.FullName)): $target")
        }
    }
}

# 汇总仓库级结果，任一公开文档失败、案例过期或链接缺失都会阻止交付
$failedDocuments = @($documentResults | Where-Object status -ne 'PASS')
$status = if (
    $failedDocuments.Count -eq 0 -and
    $scriptParseErrors.Count -eq 0 -and
    $qualityCasesCurrent -and
    $readmeStatisticsCurrent -and
    $progressiveLoadingValid -and
    $editorialProcessGateValid -and
    $paragraphAndWarningModelValid -and
    $numericAndNativeNameModelValid -and
    $naturalChineseModelValid -and
    $missingLinks.Count -eq 0
) {
    'PASS'
}
else {
    'FAIL'
}
$output = [ordered]@{
    status = $status
    markdown_file_count = $markdownFiles.Count
    failed_document_count = $failedDocuments.Count
    powershell_file_count = $powerShellFiles.Count
    powershell_parse_error_count = $scriptParseErrors.Count
    quality_cases_current = $qualityCasesCurrent
    rule_case_count = $ruleCaseCount
    quality_case_count = $qualityCaseCount
    readme_statistics_current = $readmeStatisticsCurrent
    skill_line_count = $skillLineCount
    progressive_loading_valid = $progressiveLoadingValid
    editorial_process_gate_valid = $editorialProcessGateValid
    paragraph_and_warning_model_valid = $paragraphAndWarningModelValid
    numeric_and_native_name_model_valid = $numericAndNativeNameModelValid
    natural_chinese_model_valid = $naturalChineseModelValid
    semantic_case_count = $semanticCaseCount
    minimal_pair_count = $minimalPairCount
    user_preference_count = $preferenceCount
    activation_case_count = $activationCaseCount
    fresh_generation_case_count = $freshCaseCount
    warning_count = [int](($documentResults | Measure-Object warning_count -Sum).Sum)
    missing_progressive_references = $missingProgressiveReferences
    missing_link_count = $missingLinks.Count
    documents = @($documentResults)
    powershell_parse_errors = @($scriptParseErrors)
    missing_links = @($missingLinks)
}

[pscustomobject]$output | ConvertTo-Json -Depth 8
if ($status -ne 'PASS') {
    exit 1
}
