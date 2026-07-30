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

# 建立文档开头，说明案例来源和当前检查结果
$lines = [Collections.Generic.List[string]]::new()
$lines.Add('# 完整问答案例')
$lines.Add('')
$lines.Add('这些案例来自正式质量测试文件，问题和回答均按当前测试顺序导出')
$lines.Add('')
$lines.Add("- 案例数量：$($evaluation.case_count)")
$lines.Add("- 写作检查失败数量：$($evaluation.failed_writing_case_count)")
$lines.Add("- 样本差异检查失败数量：$($evaluation.failed_coverage_check_count)")
$lines.Add('')

# 逐个写入完整问题和完整回答，不使用摘要替代正文
for ($index = 0; $index -lt $evaluation.results.Count; $index++) {
    $case = $evaluation.results[$index]
    $caseNumber = $index + 1
    $lines.Add("## $caseNumber 案例")
    $lines.Add('')
    $lines.Add("### $caseNumber.1 问题")
    $lines.Add('')
    foreach ($promptLine in ($case.prompt -split '\r?\n')) {
        $lines.Add("> $promptLine")
    }
    $lines.Add('')
    $lines.Add("### $caseNumber.2 回答")
    $lines.Add('')
    foreach ($responseLine in ($case.response -split '\r?\n')) {
        $responseHeading = [regex]::Match(
            $responseLine,
            '^(?<hash>#{2,4})\s+(?<number>\d+(?:\.\d+)*)\s+(?<title>.+)$'
        )
        if ($responseHeading.Success) {
            $headingLevel = [Math]::Min(6, $responseHeading.Groups['hash'].Value.Length + 2)
            $headingPrefix = '#' * $headingLevel
            $nestedNumber = "$caseNumber.2.$($responseHeading.Groups['number'].Value)"
            $lines.Add("$headingPrefix $nestedNumber $($responseHeading.Groups['title'].Value)")
            continue
        }
        $lines.Add($responseLine)
    }
    $lines.Add('')
}

# 使用不带字节顺序标记的 UTF-8 编码写入，保证 GitHub 正确显示中文
$utf8WithoutBom = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllLines($OutputPath, $lines, $utf8WithoutBom)
Write-Output $OutputPath
