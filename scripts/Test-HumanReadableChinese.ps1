[CmdletBinding(DefaultParameterSetName = 'Path')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Path')]
    [string]$Path,

    [Parameter(Mandatory, ParameterSetName = 'Text')]
    [string]$Text,

    [ValidateSet('Personal', 'Publication')]
    [string]$CaptionStyle = 'Personal',

    [switch]$AllowQuestionHeadings
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

function Get-NumberedChapterAtIndex([string]$Value, [int]$Index) {
    # 图表编号使用最近的二级章节编号，文档没有编号章节时返回空值
    $beforeObject = $Value.Substring(0, [Math]::Min($Index, $Value.Length))
    $chapterMatches = [regex]::Matches(
        $beforeObject,
        '(?m)^##[ \t]+(?<chapter>[1-9]\d*)[ \t]+\S.*$'
    )
    if ($chapterMatches.Count -eq 0) {
        return $null
    }
    return [int]$chapterMatches[$chapterMatches.Count - 1].Groups['chapter'].Value
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

# 多章节文档使用十进制层级编号，让标题位置和上下级关系能够被直接引用
$numberedHeadingCandidates = @(
    $headingMatches | Where-Object { $_.Groups['hash'].Value.Length -ge 2 }
)
$secondLevelHeadingCount = @(
    $numberedHeadingCandidates | Where-Object { $_.Groups['hash'].Value.Length -eq 2 }
).Count
$requiresHierarchicalNumbering = $secondLevelHeadingCount -ge 2 -or @(
    $numberedHeadingCandidates | Where-Object { $_.Groups['hash'].Value.Length -ge 3 }
).Count -gt 0
if ($requiresHierarchicalNumbering) {
    $nextNumberByParent = @{}
    foreach ($match in $numberedHeadingCandidates) {
        $level = $match.Groups['hash'].Value.Length
        $title = $match.Groups['title'].Value
        $numberMatch = [regex]::Match($title, '^(?<number>\d+(?:\.\d+)*)\s+\S')
        if (-not $numberMatch.Success) {
            $issues.Add([pscustomobject]@{
                rule = 'SECTION_HEADING_REQUIRES_HIERARCHICAL_NUMBER'
                line = Get-LineNumber $Text $match.Index
                excerpt = $title
            })
            continue
        }

        $segments = @($numberMatch.Groups['number'].Value -split '\.' | ForEach-Object { [int]$_ })
        if ($segments.Count -ne ($level - 1)) {
            $issues.Add([pscustomobject]@{
                rule = 'SECTION_NUMBER_DEPTH_MUST_MATCH_HEADING'
                line = Get-LineNumber $Text $match.Index
                excerpt = $title
            })
            continue
        }
        if ($segments | Where-Object { $_ -lt 1 }) {
            $issues.Add([pscustomobject]@{
                rule = 'SECTION_NUMBER_MUST_START_AT_ONE'
                line = Get-LineNumber $Text $match.Index
                excerpt = $title
            })
            continue
        }

        $parentKey = if ($segments.Count -eq 1) {
            'ROOT'
        } else {
            ($segments[0..($segments.Count - 2)] -join '.')
        }
        $expectedNumber = if ($nextNumberByParent.ContainsKey($parentKey)) {
            [int]$nextNumberByParent[$parentKey]
        } else {
            1
        }
        if ($segments[-1] -ne $expectedNumber) {
            $issues.Add([pscustomobject]@{
                rule = if ($expectedNumber -eq 1) {
                    'SECTION_NUMBER_MUST_START_AT_ONE'
                } else {
                    'SECTION_NUMBER_SEQUENCE_INVALID'
                }
                line = Get-LineNumber $Text $match.Index
                excerpt = $title
            })
        }
        $nextNumberByParent[$parentKey] = $segments[-1] + 1
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
$inlineCommentPatterns = @{
    csharp = '//\s*\S'
    cs = '//\s*\S'
    javascript = '//\s*\S'
    js = '//\s*\S'
    typescript = '//\s*\S'
    ts = '//\s*\S'
    java = '//\s*\S'
    c = '//\s*\S'
    cpp = '//\s*\S'
    'c++' = '//\s*\S'
    rust = '//\s*\S'
    go = '//\s*\S'
    kotlin = '//\s*\S'
    swift = '//\s*\S'
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

    # 连续的独立语句仍然属于列表式代码，不能用一条段落注释代替逐行说明
    if ($inlineCommentPatterns.ContainsKey($language)) {
        $independentLines = @(
            $bodyLines | Where-Object {
                $_ -match ';\s*(?://.*)?$' -and
                $_ -notmatch '^\s*(?://|if\b|for\b|foreach\b|while\b|switch\b|return\b|throw\b|using\b)' -and
                $_ -notmatch '[{}]'
            }
        )
        $meaningfulLines = @(
            $bodyLines | Where-Object {
                -not [string]::IsNullOrWhiteSpace($_) -and
                $_ -notmatch '^\s*(?://|[{}])'
            }
        )
        if ($independentLines.Count -ge 2 -and $independentLines.Count -eq $meaningfulLines.Count) {
            for ($codeLineIndex = 0; $codeLineIndex -lt $bodyLines.Count; $codeLineIndex++) {
                $codeLine = $bodyLines[$codeLineIndex]
                if ($codeLine -notin $independentLines) {
                    continue
                }
                if ($codeLine -notmatch $inlineCommentPatterns[$language]) {
                    $issues.Add([pscustomobject]@{
                        rule = 'INDEPENDENT_CODE_LINE_REQUIRES_INLINE_COMMENT'
                        line = (Get-LineNumber $Text $block.Groups['body'].Index) + $codeLineIndex
                        excerpt = $codeLine.Trim()
                    })
                }
            }
            continue
        }
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

# 普通标题默认陈述主题，只有明确的问答内容才允许使用疑问句标题
if (-not $AllowQuestionHeadings) {
    $questionHeadingMatches = [regex]::Matches(
        $withoutCodeBlocks,
        '(?m)^#{1,6}[ \t]+(?:[1-9]\d*(?:\.[1-9]\d*)*[ \t]+)?(?<title>[^\r\n]*(?:为什么|为何|如何|是否|什么|怎样|怎么|能否|可否|何时|哪里|哪些|谁)[^\r\n]*|[^\r\n]*[？?])[ \t]*$'
    )
    foreach ($match in $questionHeadingMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'QUESTION_HEADING_SHOULD_BE_DECLARATIVE'
            line = Get-LineNumber $withoutCodeBlocks $match.Index
            excerpt = $match.Value.Trim()
        })
    }
}

# 个人文档把表题放在表格下方，出版格式才把表题放在表格上方
$tableMatches = [regex]::Matches(
    $withoutCodeBlocks,
    '(?m)^(?<table>(?<header>\|[^\r\n]+\|)\r?\n(?<separator>\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?)(?:\r?\n\|[^\r\n]+\|)*)'
)
$globalExpectedTableNumber = 1
$expectedTableNumberByChapter = @{}
foreach ($tableMatch in $tableMatches) {
    # 同时读取表格前后的题注，才能区分题注缺失和题注位置错误
    $beforeTable = $withoutCodeBlocks.Substring(0, $tableMatch.Index)
    $previousLines = @($beforeTable -split '\r?\n')
    $previousNonblank = @($previousLines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Last 1)
    $previousTitle = if ($previousNonblank.Count -eq 1) { $previousNonblank[0].Trim() } else { '' }
    $previousTitleMatch = [regex]::Match($previousTitle, '^表\s+(?<number>\d+(?:[.-]\d+)?)\s+\S')

    $afterTable = $withoutCodeBlocks.Substring($tableMatch.Index + $tableMatch.Length)
    $nextLines = @($afterTable -split '\r?\n')
    $nextNonblank = @($nextLines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1)
    $nextTitle = if ($nextNonblank.Count -eq 1) { $nextNonblank[0].Trim() } else { '' }
    $nextTitleMatch = [regex]::Match($nextTitle, '^表\s+(?<number>\d+(?:[.-]\d+)?)\s+\S')

    # 根据文档用途选择题注位置，默认采用个人文档的视觉统一方案
    if ($CaptionStyle -eq 'Publication') {
        $title = $previousTitle
        $titleMatch = $previousTitleMatch
        $oppositeTitleMatch = $nextTitleMatch
    }
    else {
        $title = $nextTitle
        $titleMatch = $nextTitleMatch
        $oppositeTitleMatch = $previousTitleMatch
    }

    if (-not $titleMatch.Success) {
        $rule = if ($oppositeTitleMatch.Success) {
            'TABLE_TITLE_POSITION_INVALID'
        }
        else {
            'TABLE_REQUIRES_NUMBERED_TITLE'
        }
        $issues.Add([pscustomobject]@{
            rule = $rule
            line = Get-LineNumber $withoutCodeBlocks $tableMatch.Index
            excerpt = if ($oppositeTitleMatch.Success) { $oppositeTitleMatch.Value } else { $tableMatch.Groups['header'].Value }
        })
        continue
    }

    # 编号章节中的表格使用“章节号.本章序号”，无章节短文继续使用单一序号
    $tableChapter = Get-NumberedChapterAtIndex $withoutCodeBlocks $tableMatch.Index
    $tableNumber = $titleMatch.Groups['number'].Value
    $tableNumberParts = @($tableNumber -split '[.-]')
    if (@($tableNumberParts | Where-Object { [int]$_ -eq 0 }).Count -gt 0) {
        $issues.Add([pscustomobject]@{
            rule = 'TABLE_NUMBER_MUST_NOT_USE_ZERO'
            line = Get-LineNumber $withoutCodeBlocks $tableMatch.Index
            excerpt = $title
        })
        continue
    }
    if ($tableNumber.Contains('-')) {
        $issues.Add([pscustomobject]@{
            rule = 'TABLE_NUMBER_FORMAT_MUST_MATCH_SECTION'
            line = Get-LineNumber $withoutCodeBlocks $tableMatch.Index
            excerpt = $title
        })
        continue
    }
    if ($null -ne $tableChapter) {
        $chapterKey = [string]$tableChapter
        if (-not $expectedTableNumberByChapter.ContainsKey($chapterKey)) {
            $expectedTableNumberByChapter[$chapterKey] = 1
        }
        $expectedTableNumber = [int]$expectedTableNumberByChapter[$chapterKey]
        if ($tableNumberParts.Count -ne 2) {
            $issues.Add([pscustomobject]@{
                rule = 'TABLE_NUMBER_FORMAT_MUST_MATCH_SECTION'
                line = Get-LineNumber $withoutCodeBlocks $tableMatch.Index
                excerpt = $title
            })
        }
        elseif ([int]$tableNumberParts[0] -ne $tableChapter) {
            $issues.Add([pscustomobject]@{
                rule = 'TABLE_NUMBER_SECTION_MISMATCH'
                line = Get-LineNumber $withoutCodeBlocks $tableMatch.Index
                excerpt = $title
            })
        }
        elseif ([int]$tableNumberParts[1] -ne $expectedTableNumber) {
            $issues.Add([pscustomobject]@{
                rule = 'TABLE_NUMBER_SEQUENCE_INVALID'
                line = Get-LineNumber $withoutCodeBlocks $tableMatch.Index
                excerpt = $title
            })
        }
        $expectedTableNumberByChapter[$chapterKey] = $expectedTableNumber + 1
        continue
    }
    if ($tableNumberParts.Count -ne 1) {
        $issues.Add([pscustomobject]@{
            rule = 'TABLE_NUMBER_FORMAT_MUST_MATCH_SECTION'
            line = Get-LineNumber $withoutCodeBlocks $tableMatch.Index
            excerpt = $title
        })
        continue
    }
    if ([int]$tableNumberParts[0] -ne $globalExpectedTableNumber) {
        $issues.Add([pscustomobject]@{
            rule = 'TABLE_NUMBER_SEQUENCE_INVALID'
            line = Get-LineNumber $withoutCodeBlocks $tableMatch.Index
            excerpt = $title
        })
    }
    $globalExpectedTableNumber++
}

# 两种文档格式都把图片和流程图的图题放在图形下方
$figureCandidates = [Collections.Generic.List[object]]::new()
$imageMatches = [regex]::Matches($Text, '(?m)^[ \t]*!\[[^\]\r\n]*\]\([^)]+\)[ \t]*$')
foreach ($imageMatch in $imageMatches) {
    $figureCandidates.Add([pscustomobject]@{
        Index = $imageMatch.Index
        End = $imageMatch.Index + $imageMatch.Length
        Excerpt = $imageMatch.Value.Trim()
    })
}
foreach ($block in $codeBlockMatches) {
    if ($block.Groups['language'].Value.Trim() -ieq 'mermaid') {
        $figureCandidates.Add([pscustomobject]@{
            Index = $block.Index
            End = $block.Index + $block.Length
            Excerpt = 'Mermaid 流程图'
        })
    }
}
$globalExpectedFigureNumber = 1
$expectedFigureNumberByChapter = @{}
foreach ($figure in @($figureCandidates | Sort-Object Index)) {
    $afterFigure = $Text.Substring($figure.End)
    $nextLines = @($afterFigure -split '\r?\n')
    $nextNonblank = @($nextLines | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1)
    $caption = if ($nextNonblank.Count -eq 1) { $nextNonblank[0].Trim() } else { '' }
    $captionMatch = [regex]::Match($caption, '^图\s+(?<number>\d+(?:[.-]\d+)?)\s+\S')
    if (-not $captionMatch.Success) {
        $issues.Add([pscustomobject]@{
            rule = 'FIGURE_REQUIRES_NUMBERED_CAPTION'
            line = Get-LineNumber $Text $figure.Index
            excerpt = $figure.Excerpt
        })
        continue
    }

    # 图形采用与表格相同的章节编号规则，但两类对象分别计算本章序号
    $figureChapter = Get-NumberedChapterAtIndex $Text $figure.Index
    $figureNumber = $captionMatch.Groups['number'].Value
    $figureNumberParts = @($figureNumber -split '[.-]')
    if (@($figureNumberParts | Where-Object { [int]$_ -eq 0 }).Count -gt 0) {
        $issues.Add([pscustomobject]@{
            rule = 'FIGURE_NUMBER_MUST_NOT_USE_ZERO'
            line = Get-LineNumber $Text $figure.Index
            excerpt = $caption
        })
        continue
    }
    if ($figureNumber.Contains('-')) {
        $issues.Add([pscustomobject]@{
            rule = 'FIGURE_NUMBER_FORMAT_MUST_MATCH_SECTION'
            line = Get-LineNumber $Text $figure.Index
            excerpt = $caption
        })
        continue
    }
    if ($null -ne $figureChapter) {
        $chapterKey = [string]$figureChapter
        if (-not $expectedFigureNumberByChapter.ContainsKey($chapterKey)) {
            $expectedFigureNumberByChapter[$chapterKey] = 1
        }
        $expectedFigureNumber = [int]$expectedFigureNumberByChapter[$chapterKey]
        if ($figureNumberParts.Count -ne 2) {
            $issues.Add([pscustomobject]@{
                rule = 'FIGURE_NUMBER_FORMAT_MUST_MATCH_SECTION'
                line = Get-LineNumber $Text $figure.Index
                excerpt = $caption
            })
        }
        elseif ([int]$figureNumberParts[0] -ne $figureChapter) {
            $issues.Add([pscustomobject]@{
                rule = 'FIGURE_NUMBER_SECTION_MISMATCH'
                line = Get-LineNumber $Text $figure.Index
                excerpt = $caption
            })
        }
        elseif ([int]$figureNumberParts[1] -ne $expectedFigureNumber) {
            $issues.Add([pscustomobject]@{
                rule = 'FIGURE_NUMBER_SEQUENCE_INVALID'
                line = Get-LineNumber $Text $figure.Index
                excerpt = $caption
            })
        }
        $expectedFigureNumberByChapter[$chapterKey] = $expectedFigureNumber + 1
        continue
    }
    if ($figureNumberParts.Count -ne 1) {
        $issues.Add([pscustomobject]@{
            rule = 'FIGURE_NUMBER_FORMAT_MUST_MATCH_SECTION'
            line = Get-LineNumber $Text $figure.Index
            excerpt = $caption
        })
        continue
    }
    if ([int]$figureNumberParts[0] -ne $globalExpectedFigureNumber) {
        $issues.Add([pscustomobject]@{
            rule = 'FIGURE_NUMBER_SEQUENCE_INVALID'
            line = Get-LineNumber $Text $figure.Index
            excerpt = $caption
        })
    }
    $globalExpectedFigureNumber++
}

# 引用采用 IEEE 顺序编码制，正文编号和文末条目保持一一对应
$citationNarrative = [regex]::Replace($withoutCodeBlocks, '`[^`]*`', ${function:Hide-Match})
$authorYearMatches = [regex]::Matches(
    $citationNarrative,
    '(?:\(|（)(?:[A-Z][A-Za-z-]+|[\p{IsCJKUnifiedIdeographs}]{2,4})(?:\s+(?:and|&)\s+[A-Z][A-Za-z-]+)?\s*[,，]\s*(?:19|20)\d{2}[a-z]?(?:\)|）)'
)
foreach ($match in $authorYearMatches) {
    $issues.Add([pscustomobject]@{
        rule = 'NON_IEEE_CITATION_STYLE'
        line = Get-LineNumber $citationNarrative $match.Index
        excerpt = $match.Value
    })
}
$referenceEntryMatches = [regex]::Matches(
    $withoutCodeBlocks,
    '(?m)^[ \t]*\[(?<number>[1-9]\d*)\][ \t]+\S.*$'
)
$referenceNumbers = [Collections.Generic.HashSet[int]]::new()
foreach ($entry in $referenceEntryMatches) {
    [void]$referenceNumbers.Add([int]$entry.Groups['number'].Value)
}
$citationText = $withoutCodeBlocks
foreach ($entry in @($referenceEntryMatches | Sort-Object Index -Descending)) {
    $citationText = $citationText.Remove($entry.Index, $entry.Length).Insert($entry.Index, (' ' * $entry.Length))
}
$citationText = [regex]::Replace($citationText, '`[^`]*`', ${function:Hide-Match})
$citationMatches = [regex]::Matches(
    $citationText,
    '\[(?<numbers>[1-9]\d*(?:\s*,\s*[1-9]\d*)*)\](?!\()'
)
$seenCitationNumbers = [Collections.Generic.HashSet[int]]::new()
$nextCitationNumber = 1
foreach ($citation in $citationMatches) {
    $numbers = @($citation.Groups['numbers'].Value -split '\s*,\s*' | ForEach-Object { [int]$_ })
    foreach ($number in $numbers) {
        if (-not $seenCitationNumbers.Contains($number)) {
            if ($number -ne $nextCitationNumber) {
                $issues.Add([pscustomobject]@{
                    rule = 'IEEE_CITATION_ORDER_INVALID'
                    line = Get-LineNumber $citationText $citation.Index
                    excerpt = $citation.Value
                })
            }
            [void]$seenCitationNumbers.Add($number)
            $nextCitationNumber++
        }
        if (-not $referenceNumbers.Contains($number)) {
            $issues.Add([pscustomobject]@{
                rule = 'IEEE_CITATION_MISSING_REFERENCE'
                line = Get-LineNumber $citationText $citation.Index
                excerpt = $citation.Value
            })
        }
    }
}

# 操作步骤使用中文顺序词，并在相邻步骤之间保留空行
$proceduralNumericMatches = [regex]::Matches(
    $withoutCodeBlocks,
    '(?m)^[ \t]*\d+\.[ \t]+(?:先|再|最后|安装|打开|运行|执行|检查|确认|核对|配置|创建|复制|启动|停止|提交|验证|导出|部署|登录|选择|输入|下载|上传)\S*'
)
foreach ($match in $proceduralNumericMatches) {
    $issues.Add([pscustomobject]@{
        rule = 'PROCEDURAL_STEPS_SHOULD_USE_CHINESE_ORDINALS'
        line = Get-LineNumber $withoutCodeBlocks $match.Index
        excerpt = $match.Value.Trim()
    })
}
$stepMatches = [regex]::Matches($withoutCodeBlocks, '(?m)^[ \t]*第(?<number>[一二三四五六七八九十]+)步[ \t]+\S.*$')
if ($stepMatches.Count -gt 0 -and $stepMatches[0].Groups['number'].Value -ne '一') {
    $issues.Add([pscustomobject]@{
        rule = 'PROCEDURAL_STEPS_MUST_START_AT_FIRST'
        line = Get-LineNumber $withoutCodeBlocks $stepMatches[0].Index
        excerpt = $stepMatches[0].Value.Trim()
    })
}
for ($stepIndex = 1; $stepIndex -lt $stepMatches.Count; $stepIndex++) {
    $betweenSteps = $withoutCodeBlocks.Substring(
        $stepMatches[$stepIndex - 1].Index + $stepMatches[$stepIndex - 1].Length,
        $stepMatches[$stepIndex].Index - ($stepMatches[$stepIndex - 1].Index + $stepMatches[$stepIndex - 1].Length)
    )
    if ($betweenSteps -notmatch '\r?\n[ \t]*\r?\n') {
        $issues.Add([pscustomobject]@{
            rule = 'PROCEDURAL_STEPS_REQUIRE_BLANK_LINE'
            line = Get-LineNumber $withoutCodeBlocks $stepMatches[$stepIndex].Index
            excerpt = $stepMatches[$stepIndex].Value.Trim()
        })
    }
}

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
    if ($line -match '^\s*\[[1-9]\d*\]\s+\S') {
        continue
    }

    $screenedNarrativeLine = Hide-NonNarrativeZones $line
    $doubleNegativeMatches = [regex]::Matches(
        $screenedNarrativeLine,
        '(?<term>不能不|不得不|不会不|并非不|不是没有|未必不|不可能不|无法不|不无)'
    )
    foreach ($match in $doubleNegativeMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'DOUBLE_NEGATIVE_SHOULD_BE_SIMPLIFIED'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = $match.Groups['term'].Value
        })
    }

    $ambiguousFrozenVersionMatches = [regex]::Matches($screenedNarrativeLine, '项目(?:的)?冻结版本')
    foreach ($match in $ambiguousFrozenVersionMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'AMBIGUOUS_FROZEN_VERSION_OWNER'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = $match.Value
        })
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
    $structuralLine = [regex]::Replace(
        $structuralLine,
        '综合、布局、布线和时序检查',
        ${function:Hide-Match}
    )
    $withoutInlineCode = [regex]::Replace($line, '`[^`]*`', ${function:Hide-Match})
    $fieldLabelLine = [regex]::Replace(
        $withoutInlineCode,
        '[“"][^”"\r\n]{1,100}[”"]',
        ${function:Hide-Match}
    )

    $fieldLabelMatches = [regex]::Matches(
        $fieldLabelLine,
        '(?<term>作用解释\s*[：:]|名称由来\s*[：:]|[（(][^）)\r\n]{0,80}(?:类型|含义|影响)\s*[：:][^）)\r\n]{0,80}[）)])'
    )
    foreach ($match in $fieldLabelMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'FIELD_LABEL_EXPLANATION_SHOULD_BE_NATURAL_PROSE'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

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

    if ($structuralLine -match '^\s*[-*]\s+(?:先|再|优先|核对|确认|检查|找出|处理|列出)' -or
        $structuralLine -match '(?:问题可能来自|优先找出|特别要确认|先(?:核对|确认|检查|找出|处理|列出)|需要(?:核对|确认|检查|找出|处理|列出)|应该(?:核对|确认|检查|找出|处理|列出)|必须(?:核对|确认|检查|找出|处理|列出))') {
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
        $hasAbbreviationMapping = $tail -match '^\s*[一-龥][^（\r\n]{0,40}（[^）]*[A-Za-z][^）]*）'
        if (-not $hasAbbreviationMapping) {
            $issues.Add([pscustomobject]@{
                rule = 'POSSIBLY_UNEXPLAINED_FIRST_ENGLISH_TERM'
                line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
                excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
            })
        }
    }
}

# 简短标签和值属于同一逻辑框架，拆成两行会增加无意义的视线跳转
$plainLines = $withoutCodeBlocks -split '\r?\n'
for ($plainLineIndex = 0; $plainLineIndex -lt ($plainLines.Count - 1); $plainLineIndex++) {
    $labelLine = $plainLines[$plainLineIndex]
    if ($labelLine -notmatch '^[ \t]*(?:[-*][ \t]+)?[^：\r\n]{1,40}(?:为|是)：[ \t]*$') {
        continue
    }
    $valueIndex = $plainLineIndex + 1
    while ($valueIndex -lt $plainLines.Count -and [string]::IsNullOrWhiteSpace($plainLines[$valueIndex])) {
        $valueIndex++
    }
    if ($valueIndex -ge $plainLines.Count) {
        continue
    }
    $valueLine = $plainLines[$valueIndex].Trim()
    if ($valueLine.Length -le 100 -and $valueLine -notmatch '^(?:[-*]|\d+\.\s|#|\||>|```|第一步|第二步|第三步)') {
        $issues.Add([pscustomobject]@{
            rule = 'SIMPLE_KEY_VALUE_SHOULD_STAY_INLINE'
            line = $plainLineIndex + 1
            excerpt = ($labelLine.Trim() + ' ' + $valueLine)
        })
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
