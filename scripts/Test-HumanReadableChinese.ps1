[CmdletBinding(DefaultParameterSetName = 'Path')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Path')]
    [string]$Path,

    [Parameter(Mandatory, ParameterSetName = 'Text')]
    [string]$Text
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PSCmdlet.ParameterSetName -eq 'Path') {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "File not found: $Path"
    }
    $Text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
}

function Get-LineNumber([string]$Value, [int]$Index) {
    if ($Index -le 0) {
        return 1
    }
    return ([regex]::Matches($Value.Substring(0, $Index), "`n")).Count + 1
}

function Get-Excerpt([string]$Value, [int]$Index, [int]$Length) {
    $start = [Math]::Max(0, $Index - 30)
    $end = [Math]::Min($Value.Length, $Index + $Length + 70)
    return [regex]::Replace($Value.Substring($start, $end - $start), '\s+', ' ').Trim()
}

function Hide-Match([Text.RegularExpressions.Match]$Match) {
    return ' ' * $Match.Length
}

function Hide-NonNarrativeZones([string]$Value) {
    $masked = $Value
    $masked = [regex]::Replace($masked, '\$\$.*?\$\$|\$(?:\\.|[^$\r\n])+\$', ${function:Hide-Match})
    $masked = [regex]::Replace($masked, '`[^`]*`', ${function:Hide-Match})
    $masked = [regex]::Replace($masked, '!\[[^\]]*\]\([^)]+\)', ${function:Hide-Match})
    $masked = [regex]::Replace($masked, '\]\([^)]+\)', ${function:Hide-Match})
    $masked = [regex]::Replace($masked, '</?[A-Za-z][^>\r\n]*>', ${function:Hide-Match})
    $masked = [regex]::Replace($masked, 'https?://\S+|www\.\S+', ${function:Hide-Match})
    $masked = [regex]::Replace($masked, '（[^）]*）|\([^)]*\)', ${function:Hide-Match})
    $masked = [regex]::Replace(
        $masked,
        '(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)+(?![A-Za-z0-9_])',
        ${function:Hide-Match}
    )
    $masked = [regex]::Replace(
        $masked,
        '(?<!\S)[A-Za-z]:[\\/][^\s；，：]+|(?<!\S)[.]{0,2}[\\/][^\s；，：]+',
        ${function:Hide-Match}
    )
    return $masked
}

$issues = [Collections.Generic.List[object]]::new()
$period = [char]0x3002
for ($i = 0; $i -lt $Text.Length; $i++) {
    if ($Text[$i] -eq $period) {
        $issues.Add([pscustomobject]@{
            rule = 'FORBIDDEN_CHINESE_PERIOD'
            line = Get-LineNumber $Text $i
            excerpt = Get-Excerpt $Text $i 1
        })
    }
}

$headingMatches = [regex]::Matches($Text, '(?m)^(?<hash>#{1,6})\s+(?<title>.+?)\s*$')
foreach ($match in $headingMatches) {
    $title = $match.Groups['title'].Value
    if ($title -match '[/／&＆]' -or $title -match '(?:和|与|及|、)') {
        $issues.Add([pscustomobject]@{
            rule = 'PARALLEL_OR_AMBIGUOUS_HEADING'
            line = Get-LineNumber $Text $match.Index
            excerpt = $title
        })
    }
    if ($title -match '(?i)\b[A-Z]\s*/\s*[A-Z]\b') {
        $issues.Add([pscustomobject]@{
            rule = 'LETTER_SLASH_HEADING'
            line = Get-LineNumber $Text $match.Index
            excerpt = $title
        })
    }
}

$codeBlockMatches = [regex]::Matches(
    $Text,
    '(?ms)^```(?<language>[^\r\n`]*)\r?\n(?<body>.*?)^```[ \t]*$'
)
$listLikeLanguages = [Collections.Generic.HashSet[string]]::new(
    [string[]]@('powershell', 'ps1', 'bash', 'sh', 'shell', 'yaml', 'yml', 'toml', 'env', 'dotenv'),
    [StringComparer]::OrdinalIgnoreCase
)
$paragraphCommentPatterns = @{
    csharp = '^\s*//'
    cs = '^\s*//'
    javascript = '^\s*//'
    js = '^\s*//'
    typescript = '^\s*//'
    ts = '^\s*//'
    java = '^\s*//'
    c = '^\s*//'
    cpp = '^\s*//'
    'c++' = '^\s*//'
    rust = '^\s*//'
    go = '^\s*//'
    kotlin = '^\s*//'
    swift = '^\s*//'
    python = '^\s*#'
    py = '^\s*#'
    sql = '^\s*--'
    html = '^\s*<!--'
    xml = '^\s*<!--'
    css = '^\s*/\*'
    scss = '^\s*/\*'
    jsonc = '^\s*(?://|/\*)'
    mermaid = '^\s*%%'
}

foreach ($block in $codeBlockMatches) {
    $language = $block.Groups['language'].Value.Trim().ToLowerInvariant()
    $body = $block.Groups['body'].Value
    $bodyLines = $body -split '\r?\n'

    if ($language -eq 'json') {
        $issues.Add([pscustomobject]@{
            rule = 'STRICT_JSON_REQUIRES_ANNOTATED_JSONC'
            line = Get-LineNumber $Text $block.Index
            excerpt = '严格 JSON 不允许注释；交付原文件链接，并在对话中提供带注释的 JSONC 等价示例'
        })
        continue
    }

    if ($listLikeLanguages.Contains($language)) {
        for ($codeLineIndex = 0; $codeLineIndex -lt $bodyLines.Count; $codeLineIndex++) {
            $codeLine = $bodyLines[$codeLineIndex]
            if ([string]::IsNullOrWhiteSpace($codeLine) -or $codeLine -match '^\s*#') {
                continue
            }
            if ($codeLine -notmatch '\S[ \t]+#[ \t]*\S') {
                $issues.Add([pscustomobject]@{
                    rule = 'LIST_CODE_LINE_REQUIRES_INLINE_COMMENT'
                    line = (Get-LineNumber $Text $block.Groups['body'].Index) + $codeLineIndex
                    excerpt = $codeLine.Trim()
                })
            }
        }
        continue
    }

    $commentPattern = if ($paragraphCommentPatterns.ContainsKey($language)) {
        $paragraphCommentPatterns[$language]
    } else {
        '^\s*(?://|#|--|<!--|/\*)'
    }
    $paragraphStart = $true
    for ($codeLineIndex = 0; $codeLineIndex -lt $bodyLines.Count; $codeLineIndex++) {
        $codeLine = $bodyLines[$codeLineIndex]
        if ([string]::IsNullOrWhiteSpace($codeLine)) {
            $paragraphStart = $true
            continue
        }
        if (-not $paragraphStart) {
            continue
        }
        if ($codeLine -notmatch $commentPattern) {
            $issues.Add([pscustomobject]@{
                rule = 'CODE_PARAGRAPH_REQUIRES_LEADING_COMMENT'
                line = (Get-LineNumber $Text $block.Groups['body'].Index) + $codeLineIndex
                excerpt = $codeLine.Trim()
            })
        }
        $paragraphStart = $false
    }
}

$withoutCodeBlocks = [regex]::Replace($Text, '(?ms)```.*?```', '')

$unindentedBranchMatches = [regex]::Matches(
    $withoutCodeBlocks,
    '(?m)^(?<first>如果[^\r\n]+)\r?\n(?:\s*\r?\n)*(?<second>如果[^\r\n]+)'
)
foreach ($match in $unindentedBranchMatches) {
    $issues.Add([pscustomobject]@{
        rule = 'PARALLEL_BRANCHES_REQUIRE_INDENTATION'
        line = Get-LineNumber $withoutCodeBlocks $match.Index
        excerpt = Get-Excerpt $withoutCodeBlocks $match.Index $match.Length
    })
}

$branchLines = $withoutCodeBlocks -split '\r?\n'
for ($lineIndex = 0; $lineIndex -lt $branchLines.Count; $lineIndex++) {
    $branchMatch = [regex]::Match(
        $branchLines[$lineIndex],
        '^(?<indent>[ \t]*)[-*][ \t]+如果[^\r\n]+$'
    )
    if (-not $branchMatch.Success) {
        continue
    }

    $parentIndent = $branchMatch.Groups['indent'].Value.Length
    $childCount = 0
    $childLines = [Collections.Generic.List[string]]::new()
    for ($nextIndex = $lineIndex + 1; $nextIndex -lt $branchLines.Count; $nextIndex++) {
        $nextLine = $branchLines[$nextIndex]
        if ([string]::IsNullOrWhiteSpace($nextLine)) {
            continue
        }

        $childMatch = [regex]::Match(
            $nextLine,
            '^(?<indent>[ \t]*)[-*][ \t]+[^\r\n]+$'
        )
        if (-not $childMatch.Success -or $childMatch.Groups['indent'].Value.Length -le $parentIndent) {
            break
        }

        $childCount++
        $childLines.Add($nextLine.Trim())
    }

    if ($childCount -eq 1) {
        $issues.Add([pscustomobject]@{
            rule = 'SINGLE_OUTCOME_BRANCH_SHOULD_STAY_INLINE'
            line = $lineIndex + 1
            excerpt = ($branchLines[$lineIndex].Trim() + ' ' + $childLines[0])
        })
    }
}

$lineMatches = [regex]::Matches($withoutCodeBlocks, '(?m)^.*$')
$section = 0
$seenInSection = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$insideFrontmatter = $false
$frontmatterFinished = $false
$insideDisplayMath = $false
foreach ($lineMatch in $lineMatches) {
    $line = $lineMatch.Value
    if (-not $frontmatterFinished -and $lineMatch.Index -eq 0 -and $line -eq '---') {
        $insideFrontmatter = $true
        continue
    }
    if ($insideFrontmatter) {
        if ($line -eq '---') {
            $insideFrontmatter = $false
            $frontmatterFinished = $true
        }
        continue
    }

    if ($line -match '^\s*\$\$\s*$') {
        $insideDisplayMath = -not $insideDisplayMath
        continue
    }
    if ($insideDisplayMath) {
        continue
    }

    if ($line -match '^\s*(?:>|\|)') {
        continue
    }

    if ($line -notmatch '^\s*>' -and $line.TrimEnd() -match '；$') {
        $issues.Add([pscustomobject]@{
            rule = 'FORBIDDEN_LINE_END_SEMICOLON'
            line = Get-LineNumber $withoutCodeBlocks $lineMatch.Index
            excerpt = [regex]::Replace($line, '\s+', ' ').Trim()
        })
    }

    if ($line -match '^#{1,6}\s+') {
        $section++
        $seenInSection.Clear()
    }

    $parenthesisCount = ([regex]::Matches($line, '（')).Count
    if ($parenthesisCount -gt 2) {
        $issues.Add([pscustomobject]@{
            rule = 'PARENTHESIS_OVERLOAD'
            line = Get-LineNumber $withoutCodeBlocks $lineMatch.Index
            excerpt = [regex]::Replace($line, '\s+', ' ').Trim()
        })
    }

    $longExplanationMatches = [regex]::Matches($line, '（(?<inner>[^）]{161,})）')
    foreach ($longMatch in $longExplanationMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'EXPLANATION_TOO_LONG'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $longMatch.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $longMatch.Index) $longMatch.Length
        })
    }

    $narrativeLine = Hide-NonNarrativeZones $line
    $structuralLine = [regex]::Replace(
        $narrativeLine,
        '[“"][^”"\r\n]{1,100}[”"]',
        ${function:Hide-Match}
    )
    $withoutInlineCode = [regex]::Replace($line, '`[^`]*`', ${function:Hide-Match})

    $stockPhraseMatches = [regex]::Matches(
        $structuralLine,
        '^\s*(?:[-*]\s+|>\s*)?(?<term>先说结论|简单来说|换句话说|需要注意的是|值得一提的是|可以确定的是)\s*[：，,:]?'
    )
    foreach ($match in $stockPhraseMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'STOCK_META_WRITING_PHRASE'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $delayedSubjectMatches = [regex]::Matches(
        $structuralLine,
        '(?:^|[；，]\s*)(?<term>已经完成的是|需要关注的是|可以确定的是|值得注意的是|真正重要的是)'
    )
    foreach ($match in $delayedSubjectMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'POSSIBLY_DELAYED_SUBJECT'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $decorativeQuotationMatches = [regex]::Matches(
        $narrativeLine,
        '(?<lead>更像是|类似于|可以理解为|相当于|所谓|一种)\s*[“"](?<term>[^”"\r\n]{1,30})[”"]'
    )
    foreach ($match in $decorativeQuotationMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'POSSIBLY_DECORATIVE_QUOTATION'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $inlineEnumerationMatches = [regex]::Matches(
        $structuralLine,
        '(?<lead>以下|包括|分为|分别|三项|四类|五类|特别要确认|优先找出[^：:\r\n]{0,12})[：:]\s*\S+'
    )
    foreach ($match in $inlineEnumerationMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'INLINE_ENUMERATION_SHOULD_BREAK'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $inlineNounListMatches = [regex]::Matches(
        $structuralLine,
        '(?<term>[\p{IsCJKUnifiedIdeographs}A-Za-z0-9]{2,24}、[\p{IsCJKUnifiedIdeographs}A-Za-z0-9]{2,24}(?:、|或|和)[\p{IsCJKUnifiedIdeographs}A-Za-z0-9]{2,24})'
    )
    foreach ($match in $inlineNounListMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'INLINE_NOUN_ENUMERATION_SHOULD_BREAK'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $parallelNumericFactMatches = [regex]::Matches(
        $structuralLine,
        '(?<term>\d[^；\r\n]{1,100}；\s*\d[^；\r\n]{1,100})'
    )
    foreach ($match in $parallelNumericFactMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'PARALLEL_NUMERIC_FACTS_SHOULD_BREAK'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $inlineBranchMatches = [regex]::Matches(
        $structuralLine,
        '(?<lead>确认|核对|判断|检查)[^；\r\n]{0,24}是[^；\r\n]{1,30}还是[^；\r\n]{1,30}'
    )
    foreach ($match in $inlineBranchMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'INLINE_BRANCH_SHOULD_BREAK'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $wrongLeadPunctuationMatches = [regex]::Matches(
        $structuralLine,
        '(?<term>如下(?:所示)?|可以这样写|包括以下(?:内容)?|分为以下(?:情况)?|先(?:检查|处理|确认|核对)以下(?:项目|内容|事项)?|证据如下)\s*；\s*$'
    )
    foreach ($match in $wrongLeadPunctuationMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'INTRODUCER_REQUIRES_COLON'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $noncanonicalCpkMatches = [regex]::Matches(
        $narrativeLine,
        '(?<![A-Za-z0-9_])CPK(?![A-Za-z0-9_])'
    )
    foreach ($match in $noncanonicalCpkMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'NONCANONICAL_CPK_CASE'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $plainMathNotationMatches = [regex]::Matches(
        $narrativeLine,
        '(?<![A-Za-z0-9_])Cpk(?![A-Za-z0-9_])|[₀-₉ₐₑₒₓₔₕₖₗₘₙₚₛₜ⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ]|[α-ωΑ-Ω]|[≤≥≠≈∑∏√∞]|(?<![A-Za-z0-9_])[A-Za-z]\s*(?:>=|<=|=)\s*[-+A-Za-z0-9]'
    )
    foreach ($match in $plainMathNotationMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'MATH_NOTATION_SHOULD_USE_LATEX'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $stackedModifierMatches = [regex]::Matches(
        $structuralLine,
        '(?<term>(?:[^，；\r\n]{0,12}的){3,}[^，；\r\n]{0,12})'
    )
    foreach ($match in $stackedModifierMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'POSSIBLY_STACKED_DE_MODIFIERS'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $misplacedUnitMatches = [regex]::Matches(
        $withoutInlineCode,
        '（\s*(?<term>[A-Za-z]{1,8}/[A-Za-z]{1,8})\s*[，,]'
    )
    foreach ($match in $misplacedUnitMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'UNIT_ABBREVIATION_MUST_LEAD_MAPPING'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $unitMatches = [regex]::Matches(
        $narrativeLine,
        '(?<![A-Za-z0-9_])(?<term>[A-Za-z]{1,8}/[A-Za-z]{1,8})(?![A-Za-z0-9_])|(?<=\d)(?<term>[A-Za-z]{1,6})(?![A-Za-z0-9_])'
    )
    foreach ($match in $unitMatches) {
        $key = "$section|unit|$($match.Groups['term'].Value)"
        if (-not $seenInSection.Add($key)) {
            continue
        }

        $tailLength = [Math]::Min(140, $line.Length - ($match.Index + $match.Length))
        $tail = if ($tailLength -gt 0) {
            $line.Substring($match.Index + $match.Length, $tailLength)
        } else {
            ''
        }
        if ($tail -notmatch '^\s*[一-龥][^（\r\n]{0,30}（[^）]*[A-Za-z][^）]*）') {
            $issues.Add([pscustomobject]@{
                rule = 'POSSIBLY_UNEXPLAINED_UNIT_ABBREVIATION'
                line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
                excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
            })
        }
    }

    $lowercaseEnglishMatches = [regex]::Matches(
        $narrativeLine,
        '(?<![A-Za-z0-9_./\\-])(?<term>[a-z]{3,}(?:[ -]+[a-z]{3,})*)(?![A-Za-z0-9_./\\-])'
    )
    foreach ($match in $lowercaseEnglishMatches) {
        $key = "$section|lower|$($match.Groups['term'].Value)"
        if (-not $seenInSection.Add($key)) {
            continue
        }
        $issues.Add([pscustomobject]@{
            rule = 'POSSIBLY_UNTRANSLATED_LOWERCASE_ENGLISH'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    $technicalMatches = [regex]::Matches(
        $narrativeLine,
        '(?<![A-Za-z0-9_])(?:[A-Z][A-Za-z0-9_]{1,}|[a-z][A-Za-z0-9_]*[A-Z][A-Za-z0-9_]*)(?![A-Za-z0-9_])'
    )
    foreach ($match in $technicalMatches) {
        $key = "$section|$($match.Value)"
        if (-not $seenInSection.Add($key)) {
            continue
        }

        $tailLength = [Math]::Min(140, $line.Length - ($match.Index + $match.Length))
        $tail = if ($tailLength -gt 0) {
            $line.Substring($match.Index + $match.Length, $tailLength)
        } else {
            ''
        }
        $hasInternalMapping = $tail -match '^\s*（[^）]*类型：[^）]*含义：[^）]*影响：[^）]*）'
        $hasAbbreviationMapping = $tail -match '^\s*[一-龥][^（\r\n]{0,40}（[^）]*[A-Za-z][^）]*）'
        if (-not $hasInternalMapping -and -not $hasAbbreviationMapping) {
            $issues.Add([pscustomobject]@{
                rule = 'POSSIBLY_UNEXPLAINED_FIRST_ENGLISH_TERM'
                line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
                excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
            })
        }
    }
}

$result = [pscustomobject]@{
    status = if ($issues.Count -eq 0) { 'PASS' } else { 'FAIL' }
    issue_count = $issues.Count
    issues = @($issues)
}

$result | ConvertTo-Json -Depth 6
if ($issues.Count -gt 0) {
    exit 1
}
exit 0
