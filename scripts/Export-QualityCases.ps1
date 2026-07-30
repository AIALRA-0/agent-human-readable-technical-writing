[CmdletBinding()]
param(
    [string]$OutputPath = (Join-Path (Split-Path $PSScriptRoot -Parent) 'QA-CASES.md')
)

# 启用严格检查，避免变量拼写错误生成不完整文档
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 执行正式质量测试，确保导出的内容与实际通过检查的案例完全一致
$skillRoot = Split-Path $PSScriptRoot -Parent
$evaluationScript = Join-Path $skillRoot 'evals\Invoke-QualityEvaluation.20260729.ps1'
$rawResult = & $evaluationScript
if ($LASTEXITCODE -ne 0) {
    throw 'Quality evaluation failed; refusing to export stale or invalid cases'
}
$evaluation = ($rawResult -join [Environment]::NewLine) | ConvertFrom-Json

# 把本轮新增案例放在历史回归案例之前，让读者能够直接看到最近增加的验证内容
$currentGeneration = $evaluation.current_generation
$currentCases = @($evaluation.results | Where-Object introduced_in -eq $currentGeneration)
$historicalCases = @($evaluation.results | Where-Object introduced_in -ne $currentGeneration)
$orderedCases = @($currentCases) + @($historicalCases)

# 建立文档开头，说明案例来源、导出调整和当前检查结果
$lines = [Collections.Generic.List[string]]::new()
$lines.Add('# 完整问答案例')
$lines.Add('')
$lines.Add('这些案例来自正式质量测试文件，本轮新增案例排在历史回归案例之前')
$lines.Add('')
$lines.Add('## 1 案例构成')
$lines.Add('')
$lines.Add("- 全部案例数量：$($evaluation.case_count)")
$lines.Add("- 本轮新增案例数量：$($currentCases.Count)")
$lines.Add("- 历史回归案例数量：$($historicalCases.Count)")
$lines.Add("- 写作检查失败数量：$($evaluation.failed_writing_case_count)")
$lines.Add("- 样本差异检查失败数量：$($evaluation.failed_coverage_check_count)")
$lines.Add('')
$lines.Add('质量测试源文件保留每个回答的原始标题和图表编号')
$lines.Add('')
$lines.Add('导出程序只调整合并文档中的标题层级和图表编号，让图表编号与所属一级章节保持一致')
$lines.Add('')
$lines.Add('## 2 完整问答')
$lines.Add('')

# 逐个写入完整问题和完整回答，并分别累计表格编号和图形编号
$tableNumber = 0
$figureNumber = 0
for ($index = 0; $index -lt $orderedCases.Count; $index++) {
    $case = $orderedCases[$index]
    $caseNumber = $index + 1
    $caseGroup = if ($case.introduced_in -eq $currentGeneration) { '本轮新增案例' } else { '历史回归案例' }
    $lines.Add("### 2.$caseNumber $caseGroup")
    $lines.Add('')
    $lines.Add("案例来源标识为：``$($case.id)``")
    $lines.Add('')
    $lines.Add("#### 2.$caseNumber.1 问题")
    $lines.Add('')
    foreach ($promptLine in ($case.prompt -split '\r?\n')) {
        $lines.Add("> $promptLine")
    }
    $lines.Add('')
    $lines.Add("#### 2.$caseNumber.2 回答")
    $lines.Add('')
    $lines.Add("<!-- caption-style: $($case.caption_style.ToLowerInvariant()) -->")
    $lines.Add('')
    foreach ($responseLine in ($case.response -split '\r?\n')) {
        $responseHeading = [regex]::Match(
            $responseLine,
            '^(?<hash>#{2,4})\s+(?<number>\d+(?:\.\d+)*)\s+(?<title>.+)$'
        )
        if ($responseHeading.Success) {
            $headingLevel = [Math]::Min(6, $responseHeading.Groups['hash'].Value.Length + 3)
            $headingPrefix = '#' * $headingLevel
            $nestedNumber = "2.$caseNumber.2.$($responseHeading.Groups['number'].Value)"
            $lines.Add("$headingPrefix $nestedNumber $($responseHeading.Groups['title'].Value)")
            continue
        }
        $tableCaption = [regex]::Match(
            $responseLine,
            '^(?<prefix>\s*)表\s+\d+(?:[.-]\d+)?\s+(?<title>\S.*)$'
        )
        if ($tableCaption.Success) {
            $tableNumber++
            $lines.Add("$($tableCaption.Groups['prefix'].Value)表 2.$tableNumber $($tableCaption.Groups['title'].Value)")
            continue
        }
        $figureCaption = [regex]::Match(
            $responseLine,
            '^(?<prefix>\s*)图\s+\d+(?:[.-]\d+)?\s+(?<title>\S.*)$'
        )
        if ($figureCaption.Success) {
            $figureNumber++
            $lines.Add("$($figureCaption.Groups['prefix'].Value)图 2.$figureNumber $($figureCaption.Groups['title'].Value)")
            continue
        }
        $lines.Add($responseLine)
    }
    $lines.Add('')
    $lines.Add('<!-- caption-style: end -->')
    $lines.Add('')
}

# 使用不带字节顺序标记的 UTF-8 编码写入，保证 GitHub 正确显示中文
$utf8WithoutBom = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllLines($OutputPath, $lines, $utf8WithoutBom)
Write-Output $OutputPath
