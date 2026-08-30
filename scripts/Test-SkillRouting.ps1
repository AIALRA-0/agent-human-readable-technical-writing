[CmdletBinding()]
param()

# 这个测试固定触发描述、隐式调用开关和轻量执行边界，防止后续维护把写作 Skill 再次扩大成无关工作流
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$skillRoot = Split-Path $PSScriptRoot -Parent
$skillPath = Join-Path $skillRoot 'SKILL.md'
$metadataPath = Join-Path $skillRoot 'agents\openai.yaml'
$skillText = Get-Content -LiteralPath $skillPath -Raw -Encoding UTF8
$metadataText = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8
$failures = [Collections.Generic.List[string]]::new()

# 描述在完整正文加载前决定隐式匹配，因此必须把中文写作任务和高区分度触发词放在同一行
$descriptionMatch = [regex]::Match($skillText, '(?m)^description:\s*(?<value>.+)$')
if (-not $descriptionMatch.Success) {
    $failures.Add('SKILL.md 缺少触发描述')
}
else {
    $description = $descriptionMatch.Groups['value'].Value
    foreach ($keyword in @('中文回答', '解释', '改写', '状态', '计划', '报告', '错误', '数字', '结论', '建议')) {
        if ($description -notmatch [regex]::Escape($keyword)) {
            $failures.Add("触发描述缺少关键词：$keyword")
        }
    }
    foreach ($boundary in @('非中文单词', '纯数字', '纯 JSON', '不得触发')) {
        if ($description -notmatch [regex]::Escape($boundary)) {
            $failures.Add("触发描述缺少边界：$boundary")
        }
    }
}

# 允许隐式调用后，用户不写技能名称的中文写作请求才能依据描述自动加载本技能
if ($metadataText -notmatch '(?m)^\s*allow_implicit_invocation:\s*true\s*$') {
    $failures.Add('agents/openai.yaml 没有启用隐式调用')
}

# 普通对话只执行轻量自检，强制每次运行仓库门禁会拉长回答并降低实际遵守度
if ($skillText -match '每一条用户可见中文内容都属于检查对象' -or $skillText -match '短回复和进度消息不能跳过') {
    $failures.Add('SKILL.md 仍然把仓库门禁强加给普通回答')
}

[pscustomobject][ordered]@{
    status = if ($failures.Count -eq 0) { 'PASS' } else { 'FAIL' }
    check_count = 16
    failure_count = $failures.Count
    failures = @($failures)
} | ConvertTo-Json -Depth 6

if ($failures.Count -gt 0) {
    exit 1
}
