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
    # 完整案例文档属于问答页面，正式评估仍会逐个限制普通案例中的疑问句标题
    $lintArguments = @{
        Path = $file.FullName
    }
    if ($file.FullName -eq $qualityCases) {
        $lintArguments.AllowQuestionHeadings = $true
    }
    $lintResult = (& $linter @lintArguments | Out-String) | ConvertFrom-Json
    $documentResults.Add([pscustomobject]@{
        path = [IO.Path]::GetRelativePath($skillRoot, $file.FullName)
        status = $lintResult.status
        issue_count = $lintResult.issue_count
        rules = @($lintResult.issues | ForEach-Object { $_.rule })
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

# 核心规则、复杂报告规则和自动检查器必须同时保留编辑过程元叙述门禁
$complexReportText = Get-Content -LiteralPath (Join-Path $skillRoot 'references\complex-reports.md') -Raw -Encoding UTF8
$linterText = Get-Content -LiteralPath $linter -Raw -Encoding UTF8
$editorialProcessGateValid = (
    $skillText -match '编辑过程元叙述' -and
    $complexReportText -match '编辑过程边界' -and
    $linterText -match 'EDITORIAL_PROCESS_META_NARRATIVE_FORBIDDEN' -and
    $linterText -match 'AllowEditorialProcessNarrative'
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
