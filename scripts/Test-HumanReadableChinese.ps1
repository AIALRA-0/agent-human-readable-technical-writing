[CmdletBinding(DefaultParameterSetName = 'Path')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Path')]
    [string]$Path,

    [Parameter(Mandatory, ParameterSetName = 'Text')]
    [string]$Text,

    [ValidateSet('Personal', 'Publication')]
    [string]$CaptionStyle = 'Personal',

    [string[]]$RequiredTerm = @(),

    [switch]$AllowQuestionHeadings,

    [switch]$AllowEditorialProcessNarrative
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PSCmdlet.ParameterSetName -eq 'Path') {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "File not found: $Path"
    }
    $Text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
}

# 统一不同操作系统产生的换行符，避免同一文档在本地和远程检查环境得到不同结果
$Text = $Text -replace "`r`n", "`n" -replace "`r", "`n"

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
    $masked = [regex]::Replace($masked, '(?s)<!--.*?-->', ${function:Hide-Match})
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

function Test-InCenteredContainer([string]$Value, [int]$Index) {
    # 解析当前位置之前仍未闭合的容器，确认对象或题注处于页面居中区域
    $prefix = $Value.Substring(0, [Math]::Min($Index, $Value.Length))
    $containerStack = [Collections.Generic.List[bool]]::new()
    $containerMatches = [regex]::Matches($prefix, '(?is)<div\b[^>]*>|</div\s*>')
    foreach ($containerMatch in $containerMatches) {
        if ($containerMatch.Value -match '(?is)^</div') {
            if ($containerStack.Count -gt 0) {
                $containerStack.RemoveAt($containerStack.Count - 1)
            }
            continue
        }
        $isCentered = $containerMatch.Value -match '(?i)\balign\s*=\s*(?:"center"|''center''|center)'
        $containerStack.Add($isCentered)
    }
    return $containerStack.Contains($true)
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
$warnings = [Collections.Generic.List[object]]::new()
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
    $currentNumberByLevel = @{}
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

        if ($segments.Count -gt 1) {
            $parentLevel = $level - 1
            $actualParent = $segments[0..($segments.Count - 2)] -join '.'
            $expectedParent = if ($currentNumberByLevel.ContainsKey($parentLevel)) {
                $currentNumberByLevel[$parentLevel] -join '.'
            } else {
                ''
            }
            if ($actualParent -ne $expectedParent) {
                $issues.Add([pscustomobject]@{
                    rule = 'SECTION_NUMBER_PARENT_MISMATCH'
                    line = Get-LineNumber $Text $match.Index
                    excerpt = $title
                })
            }
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
        $currentNumberByLevel[$level] = $segments
        foreach ($deeperLevel in @($currentNumberByLevel.Keys | Where-Object { [int]$_ -gt $level })) {
            $currentNumberByLevel.Remove($deeperLevel)
        }
    }
}

$codeBlockMatches = [regex]::Matches(
    $Text,
    '(?ms)^```(?<language>[^\r\n`]*)\r?\n(?<body>.*?)^```[ \t]*\r?$'
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

# 全部文档把表题放在表格上方，图题继续放在图形下方
$tableMatches = [regex]::Matches(
    $withoutCodeBlocks,
    '(?m)^(?<table>(?<header>\|[^\r\n]+\|)\r?\n(?<separator>\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?)(?:\r?\n\|[^\r\n]+\|)*)'
)
$globalExpectedTableNumber = 1
$expectedTableNumberByChapter = @{}
foreach ($tableMatch in $tableMatches) {
    if (-not (Test-InCenteredContainer $withoutCodeBlocks $tableMatch.Index)) {
        $issues.Add([pscustomobject]@{
            rule = 'TABLE_SHOULD_BE_CENTERED'
            line = Get-LineNumber $withoutCodeBlocks $tableMatch.Index
            excerpt = $tableMatch.Groups['header'].Value
        })
    }

    # 同时读取表格前后的题注，才能区分题注缺失和题注位置错误
    $beforeTable = $withoutCodeBlocks.Substring(0, $tableMatch.Index)
    # 允许表题与表格之间只隔着居中容器开标签，以便识别容器外的表题
    $previousTitleCandidate = [regex]::Match(
        $beforeTable,
        '(?is)(?<title>表\s+\d+(?:[.-]\d+)?\s+[^\r\n]+)\s*(?:<div\b[^>]*>\s*)*$'
    )
    $previousTitle = if ($previousTitleCandidate.Success) {
        $previousTitleCandidate.Groups['title'].Value.Trim()
    } else {
        ''
    }
    $previousTitleMatch = [regex]::Match($previousTitle, '^表\s+(?<number>\d+(?:[.-]\d+)?)\s+\S')

    $afterTable = $withoutCodeBlocks.Substring($tableMatch.Index + $tableMatch.Length)
    # 读取表格下方的题注，只用于识别题注位置错误
    $nextTitleCandidate = [regex]::Match(
        $afterTable,
        '(?is)^\s*(?:</div\s*>\s*)*(?<title>表\s+\d+(?:[.-]\d+)?\s+[^\r\n]+)'
    )
    $nextTitle = if ($nextTitleCandidate.Success) {
        $nextTitleCandidate.Groups['title'].Value.Trim()
    } else {
        ''
    }
    $nextTitleMatch = [regex]::Match($nextTitle, '^表\s+(?<number>\d+(?:[.-]\d+)?)\s+\S')

    # CaptionStyle 参数继续保留兼容旧调用，但所有格式都要求表题位于表格上方
    $title = $previousTitle
    $titleMatch = $previousTitleMatch
    $oppositeTitleMatch = $nextTitleMatch
    $titleIndex = if ($previousTitleCandidate.Success) {
        $previousTitleCandidate.Groups['title'].Index
    } else {
        -1
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

    if ($titleIndex -lt 0 -or -not (Test-InCenteredContainer $withoutCodeBlocks $titleIndex)) {
        $issues.Add([pscustomobject]@{
            rule = 'VISUAL_CAPTION_SHOULD_BE_CENTERED'
            line = Get-LineNumber $withoutCodeBlocks $tableMatch.Index
            excerpt = $title
        })
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
$imageMatches = [regex]::Matches($Text, '(?m)^[ \t]*!\[[^\]\r\n]*\]\([^)]+\)[ \t]*\r?$')
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
    if (-not (Test-InCenteredContainer $Text $figure.Index)) {
        $issues.Add([pscustomobject]@{
            rule = 'FIGURE_SHOULD_BE_CENTERED'
            line = Get-LineNumber $Text $figure.Index
            excerpt = $figure.Excerpt
        })
    }

    $afterFigure = $Text.Substring($figure.End)
    # 允许先结束图形自己的居中容器，再读取容器外的图题，以便准确报告题注没有共同居中
    $followingCaptionMatch = [regex]::Match(
        $afterFigure,
        '(?is)^\s*(?:</div\s*>\s*)*(?<caption>图\s+\d+(?:[.-]\d+)?\s+[^\r\n]+)'
    )
    $caption = if ($followingCaptionMatch.Success) {
        $followingCaptionMatch.Groups['caption'].Value.Trim()
    } else {
        ''
    }
    $captionMatch = [regex]::Match($caption, '^图\s+(?<number>\d+(?:[.-]\d+)?)\s+\S')
    if (-not $captionMatch.Success) {
        $issues.Add([pscustomobject]@{
            rule = 'FIGURE_REQUIRES_NUMBERED_CAPTION'
            line = Get-LineNumber $Text $figure.Index
            excerpt = $figure.Excerpt
        })
        continue
    }

    $captionIndex = if ($followingCaptionMatch.Success) {
        $figure.End + $followingCaptionMatch.Groups['caption'].Index
    } else {
        -1
    }
    if ($captionIndex -lt 0 -or -not (Test-InCenteredContainer $Text $captionIndex)) {
        $issues.Add([pscustomobject]@{
            rule = 'VISUAL_CAPTION_SHOULD_BE_CENTERED'
            line = Get-LineNumber $Text $figure.Index
            excerpt = $caption
        })
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

# 操作步骤使用项目符号和中文顺序词，并在相邻顶层步骤之间保留空行
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
$bareStepMatches = [regex]::Matches(
    $withoutCodeBlocks,
    '(?m)^[ \t]*(?<step>第[一二三四五六七八九十]+步(?:[，,:：]|[ \t]+)\S.*)$'
)
foreach ($match in $bareStepMatches) {
    $issues.Add([pscustomobject]@{
        rule = 'PROCEDURAL_STEPS_REQUIRE_LIST'
        line = Get-LineNumber $withoutCodeBlocks $match.Index
        excerpt = $match.Groups['step'].Value.Trim()
    })
}

$allBulletStepMatches = [regex]::Matches(
    $withoutCodeBlocks,
    '(?m)^(?<indent>[ \t]*)[-*][ \t]+第(?<number>[一二三四五六七八九十]+)步(?<tail>[^\r\n]*)$'
)
foreach ($match in $allBulletStepMatches) {
    if ($match.Groups['tail'].Value -notmatch '^[，：]\S') {
        $issues.Add([pscustomobject]@{
            rule = 'PROCEDURAL_STEP_REQUIRES_COMMA_OR_COLON'
            line = Get-LineNumber $withoutCodeBlocks $match.Index
            excerpt = $match.Value.Trim()
        })
    }
}

$stepMatches = [regex]::Matches(
    $withoutCodeBlocks,
    '(?m)^(?<indent>[ \t]*)[-*][ \t]+第(?<number>[一二三四五六七八九十]+)步(?<punct>[，：])\S.*$'
)
if ($stepMatches.Count -gt 0 -and $stepMatches[0].Groups['number'].Value -ne '一') {
    $issues.Add([pscustomobject]@{
        rule = 'PROCEDURAL_STEPS_MUST_START_AT_FIRST'
        line = Get-LineNumber $withoutCodeBlocks $stepMatches[0].Index
        excerpt = $stepMatches[0].Value.Trim()
    })
}
foreach ($stepMatch in $stepMatches) {
    if ($stepMatch.Groups['punct'].Value -ne '：') {
        continue
    }
    $stepLineEnd = $stepMatch.Index + $stepMatch.Length
    $remainingText = $withoutCodeBlocks.Substring($stepLineEnd)
    $nextContentMatch = [regex]::Match($remainingText, '(?m)^\r?\n(?:[ \t]*\r?\n)*(?<line>[^\r\n]+)')
    $parentIndentLength = $stepMatch.Groups['indent'].Value.Length
    $hasIndentedChild = $nextContentMatch.Success -and
        $nextContentMatch.Groups['line'].Value -match '^(?<indent>[ \t]+)[-*][ \t]+\S' -and
        $Matches['indent'].Length -gt $parentIndentLength
    if (-not $hasIndentedChild) {
        $issues.Add([pscustomobject]@{
            rule = 'PROCEDURAL_COLON_STEP_REQUIRES_INDENTED_CONTENT'
            line = Get-LineNumber $withoutCodeBlocks $stepMatch.Index
            excerpt = $stepMatch.Value.Trim()
        })
    }
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
$seenInDocument = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$insideFrontmatter = $false
$frontmatterFinished = $false
$insideDisplayMath = $false
$boundaryClaimCountInUnit = 0
$numericSourcePattern = '(?:来自|依据|根据|取自|读取自|记录于|用户(?:本次)?提供|原始材料(?:显示|记录|提供)|(?:系统|界面|日志|配置文件|仪器|监测记录|业务记录|数据库)(?:显示|记录|提供|设定)|实测(?:显示|得到)|测量(?:显示|得到)|统计(?:显示|得到)|由[^；，\r\n]{1,60}(?:计算|换算|推导)|(?:模型|公式|系统|脚本|程序)[^；，\r\n]{0,30}(?:计算|换算|推导)|计算结果|经验估计|经验值|估计值|假设值|来源待核对|\[[1-9]\d*\])'
$documentNumericSourcePattern = '(?:本文|本报告|本次(?:回答|分析|报告)?|以下|后续)(?:中|所用|使用)?(?:的|全部|所有)?数值[^；\r\n]{0,100}' + $numericSourcePattern
$hasDocumentNumericProvenance = $withoutCodeBlocks -match $documentNumericSourcePattern
$numericSourceAvailableInSection = $false

# 在整份正文上扫描否定先行转折，覆盖同一行、跨行和跨段复发
$negativeContrastNarrative = Hide-NonNarrativeZones $withoutCodeBlocks
$negativeContrastNarrative = [regex]::Replace(
    $negativeContrastNarrative,
    '(?m)^[ \t]*(?:>|\|).*$|^[ \t]*\[[1-9]\d*\][ \t]+.*$',
    ${function:Hide-Match}
)
$negativeContrastScanText = $negativeContrastNarrative.Replace([char]10, [char]32)
$negativeFirstContrastPattern = '(?<term>(?:不是|并非)(?:(?![；;。！？!?#]).){1,220}?(?:而是|真正(?:的)?(?:原因|问题|重点|关键)?(?:是|在于))|(?:重点|关键|问题)?不在于(?:(?![；;。！？!?#]).){1,220}?(?:而在于|真正(?:的)?(?:原因|问题|重点|关键)?(?:是|在于)))'
$negativeFirstContrastMatches = [regex]::Matches(
    $negativeContrastScanText,
    $negativeFirstContrastPattern
)
foreach ($match in $negativeFirstContrastMatches) {
    $issues.Add([pscustomobject]@{
        rule = 'NEGATIVE_FIRST_CONTRAST_SHOULD_BE_DIRECT'
        line = Get-LineNumber $withoutCodeBlocks $match.Index
        excerpt = Get-Excerpt $withoutCodeBlocks $match.Index $match.Length
    })
}

# 最终文档默认禁止汇报文档正在怎样编写，明确的写作进度任务可以通过开关保留这类内容
if (-not $AllowEditorialProcessNarrative) {
    $editorialProcessPattern = '(?<term>文档状态[：:](?:(?![。！？!?#]).){0,240}?(?:后续|其余)(?:章节|部分|内容)(?:(?![。！？!?#]).){0,120}?(?:补充|完善|编写|更新)|(?:后续|其余)(?:章节|部分)(?:(?![。！？!?#]).){0,120}?(?:继续|另行|逐步|随后)?(?:补充|完善|编写|更新)|(?:本节|本章|此处)(?:(?![。！？!?#]).){0,40}?(?:先)?(?:占位|待补充|稍后补充)|(?:本文|本报告|本章|本节|当前文档)(?:(?![。！？!?#]).){0,100}?(?:后续|稍后|以后)(?:(?![。！？!?#]).){0,80}?(?:补充|完善|编写|更新)|(?:第[一二三四五六七八九十百\d]+(?:章|节)|本章|本节|章节)(?:(?![。！？!?#]).){0,60}?(?:下次|下一次|下一轮|以后|稍后|后续)(?:(?![。！？!?#]).){0,40}?(?:再写|再补|填写|更新|补充|完善|添加)|(?:这一段|该段|本段|此处)(?:(?![。！？!?#]).){0,40}?(?:暂留空白|留空|空着)(?:(?![。！？!?#]).){0,60}?(?:再填|填写|补写|补充)|(?:报告|文档|正文)(?:(?![。！？!?#]).){0,40}?(?:目前|当前)?(?:只|仅)(?:写完|写了|整理完|完成)(?:(?![。！？!?#]).){0,80}?(?:以后|稍后|下一轮|下次)(?:(?![。！？!?#]).){0,30}?(?:添加|补充|再写|再补)|(?:报告|文档|正文|本章|本节)(?:(?![。！？!?#]).){0,50}?(?:先放到这里|暂时写到这里|先写到这里)(?:(?![。！？!?#]).){0,50}?(?:下一轮|下次|稍后|以后)?(?:(?![。！？!?#]).){0,20}?(?:继续|再写|补充))'
    $editorialProcessMatches = [regex]::Matches(
        $negativeContrastScanText,
        $editorialProcessPattern
    )
    foreach ($match in $editorialProcessMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'EDITORIAL_PROCESS_META_NARRATIVE_FORBIDDEN'
            line = Get-LineNumber $withoutCodeBlocks $match.Index
            excerpt = Get-Excerpt $withoutCodeBlocks $match.Index $match.Length
        })
    }
}

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
        $numericSourceAvailableInSection = $false
        $boundaryClaimCountInUnit = 0
    }

    # 识别能够直接改成准确动词的名词化结构，同时保留执行命令和任务完成等真实操作状态
    $weakNominalizedVerbMatches = [regex]::Matches(
        $screenedNarrativeLine,
        '(?<term>进行(?:了|过|着)?[^，；！？\r\n]{0,8}(?:分析|检查|验证|测试|评估|调查|讨论|说明|处理|部署|配置|计算|比较|审核|审查|复核|确认|记录|编写|整理|研究|测量|操作|试验|练习|上线)|执行(?:了|过|着)?(?:分析|检查|验证|测试|评估|调查|讨论|说明|比较|审核|审查|复核|确认|研究|测量|试验)|完成(?:了)?对[^，；！？\r\n]{1,30}的(?:分析|检查|验证|测试|评估|调查|部署|配置|审核|审查|复核|编写|整理|研究|测量))'
    )
    foreach ($match in $weakNominalizedVerbMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'WEAK_NOMINALIZED_VERB_SHOULD_BE_PRECISE'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = $match.Groups['term'].Value
        })
    }

    # 把同时承担多次逻辑转折的超长正文列为拆句候选，避免使用二十五字统一硬上限
    if ($line -notmatch '^#{1,6}\s+') {
        $chineseCharacterCount = ([regex]::Matches(
            $screenedNarrativeLine,
            '[\p{IsCJKUnifiedIdeographs}]'
        )).Count
        $logicalTurnCount = ([regex]::Matches($screenedNarrativeLine, '[，；]')).Count
        if ($chineseCharacterCount -gt 55 -and $logicalTurnCount -ge 2) {
            $issues.Add([pscustomobject]@{
                rule = 'OVERLONG_NESTED_SENTENCE_SHOULD_SPLIT'
                line = Get-LineNumber $withoutCodeBlocks $lineMatch.Index
                excerpt = [regex]::Replace($line, '\s+', ' ').Trim()
            })
        }
    }

    # 同一标题范围内只完整申明一次证据或发布边界，后续改用正向范围或直接引用
    $boundaryClaimMatches = [regex]::Matches(
        $screenedNarrativeLine,
        '(?<term>不代表|不等于|不能证明|并不表示)'
    )
    foreach ($match in $boundaryClaimMatches) {
        if ($boundaryClaimCountInUnit -gt 0) {
            $issues.Add([pscustomobject]@{
                rule = 'REPEATED_DEFENSIVE_BOUNDARY_SHOULD_CONSOLIDATE'
                line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
                excerpt = $match.Groups['term'].Value
            })
        }
        $boundaryClaimCountInUnit++
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

    # 一条来源说明可以覆盖同一章节中紧随其后的一组连续数值
    if ($fieldLabelLine -match $numericSourcePattern) {
        $numericSourceAvailableInSection = $true
    }

    # 业务数值参与判断前必须写明来自记录、计算、应用系统、用户输入或经验估计
    $numericClaimLine = [regex]::Replace($line, '`[^`]*`', ${function:Hide-Match})
    $numericClaimLine = [regex]::Replace($numericClaimLine, '!\[[^\]]*\]\([^)]+\)', ${function:Hide-Match})
    $numericClaimLine = [regex]::Replace($numericClaimLine, '\[[^\]]+\]\([^)]+\)', ${function:Hide-Match})
    $numericClaimLine = [regex]::Replace($numericClaimLine, 'https?://\S+|www\.\S+', ${function:Hide-Match})
    $numericClaimLine = [regex]::Replace($numericClaimLine, '(?:图|表)\s*\d+(?:\.\d+)?|第\s*\d+\s*章|U\+\d+', ${function:Hide-Match})
    $numericClaimLine = [regex]::Replace($numericClaimLine, '\$(?<math>[^$\r\n]+)\$', '${math}')
    $isStructuralNumericLine = (
        $line -match '^\s*#{1,6}\s+' -or
        $line -match '^\s*\[[1-9]\d*\]\s+\S' -or
        $line -match '^\s*(?:图|表)\s+[1-9]\d*(?:\.[1-9]\d*)?\s+\S' -or
        $line -match '^\s*[-*]\s+第[一二三四五六七八九十]+步[，：]' -or
        $line -match '(?:版本|器件(?:名称|型号)?|内部标识)(?:冻结|设定|记录)?为\s*[：:]' -or
        $line -match '状态码\s*\$?\d+\$?'
    )
    $numericClaimMatches = @(
        if (-not $isStructuralNumericLine) {
            [regex]::Matches($numericClaimLine, '(?<![A-Za-z0-9_.])\d+(?:\.\d+)?(?![A-Za-z0-9_.])')
        }
    )
    if (
        $numericClaimMatches.Count -gt 0 -and
        -not $hasDocumentNumericProvenance -and
        -not $numericSourceAvailableInSection -and
        $fieldLabelLine -notmatch $numericSourcePattern
    ) {
        $firstNumericMatch = $numericClaimMatches[0]
        $issues.Add([pscustomobject]@{
            rule = 'NUMERIC_CLAIM_REQUIRES_PROVENANCE'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $firstNumericMatch.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $firstNumericMatch.Index) $firstNumericMatch.Length
        })
    }

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

    $emptyLeadMatches = [regex]::Matches(
        $structuralLine,
        '^\s*(?:[-*]\s+|>\s*)?(?<term>本(?:项目|报告|文档|节|章)的?准确表述如下|以下是对当前情况的具体说明|现将有关情况说明如下|本(?:节|章|文|报告)将(?:进行)?(?:说明|介绍|阐述|分析))\s*[：，,:]?\s*$'
    )
    foreach ($match in $emptyLeadMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'LOW_INFORMATION_LEAD_SHOULD_BE_REMOVED'
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

    # 多个对象后紧接单数代词时，读者无法确定代词实际指向哪个对象
    $ambiguousPronounMatches = [regex]::Matches(
        $structuralLine,
        '(?<term>[^，；\r\n]{1,28}(?:和|与|及)[^，；\r\n]{1,28}(?:都|同时|分别)?[^；\r\n]{0,18}[；，]\s*(?:它|其|该对象|该系统))'
    )
    foreach ($match in $ambiguousPronounMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'POSSIBLY_AMBIGUOUS_PRONOUN_REFERENCE'
            line = Get-LineNumber $withoutCodeBlocks ($lineMatch.Index + $match.Index)
            excerpt = Get-Excerpt $withoutCodeBlocks ($lineMatch.Index + $match.Index) $match.Length
        })
    }

    # 完成条件后直接出现发布或交付动作时，需要补充实际执行该动作的主体
    $missingActionSubjectMatches = [regex]::Matches(
        $structuralLine,
        '(?:^|[；，]\s*)(?<term>[^，；\r\n]{0,16}(?:检查|验证|测试|审核|审批|扫描|部署|处理)完成后\s*(?:就会|就|将|会|需要|应当)(?:发布|交付|通知|删除|覆盖|生成|发送|提交))'
    )
    foreach ($match in $missingActionSubjectMatches) {
        $issues.Add([pscustomobject]@{
            rule = 'POSSIBLY_MISSING_ACTION_SUBJECT'
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
        $key = "unit|$($match.Groups['term'].Value)"
        if (-not $seenInDocument.Add($key)) {
            continue
        }

        $tailLength = [Math]::Min(140, $line.Length - ($match.Index + $match.Length))
        $tail = if ($tailLength -gt 0) {
            $line.Substring($match.Index + $match.Length, $tailLength)
        } else {
            ''
        }
        if ($tail -notmatch '^\s*[一-龥][^（\r\n]{0,30}（[^）]*[A-Za-z][^）]*）') {
            $warnings.Add([pscustomobject]@{
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
        $key = "lower|$($match.Groups['term'].Value)"
        if (-not $seenInDocument.Add($key)) {
            continue
        }
        $warnings.Add([pscustomobject]@{
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
        $key = "term|$($match.Value)"
        if (-not $seenInDocument.Add($key)) {
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
            $warnings.Add([pscustomobject]@{
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

foreach ($term in @($RequiredTerm)) {
    if ([string]::IsNullOrWhiteSpace($term)) {
        continue
    }
    $termIndex = $Text.IndexOf($term, [StringComparison]::Ordinal)
    if ($termIndex -lt 0) {
        $issues.Add([pscustomobject]@{
            rule = 'ORIGINAL_TERM_MUST_BE_RETAINED'
            line = 1
            excerpt = $term
        })
        continue
    }

    # 首次保留术语后必须立即出现名称映射或自然解释，避免原词被机械贴回正文
    $tailStart = $termIndex + $term.Length
    $tailLength = [Math]::Min(220, $Text.Length - $tailStart)
    $tail = if ($tailLength -gt 0) {
        $Text.Substring($tailStart, $tailLength)
    } else {
        ''
    }
    $chineseCharacterCount = [regex]::Matches($tail, '[\p{IsCJKUnifiedIdeographs}]').Count
    $hasNameMapping = $tail -match '^\s*`?\s*[一-龥][^（\r\n]{0,50}（[^）]*[A-Za-z][^）]*）'
    $hasNaturalExplanation = $tail -match '(?:表示|是|指|负责|用于|说明|意味着|会|决定|属于|记录|包含|比较|统计|规定|转换|这个|其中|名称)'
    if ($chineseCharacterCount -lt 8 -or (-not $hasNameMapping -and -not $hasNaturalExplanation)) {
        $issues.Add([pscustomobject]@{
            rule = 'ORIGINAL_TERM_REQUIRES_EXPLANATION'
            line = Get-LineNumber $Text $termIndex
            excerpt = Get-Excerpt $Text $termIndex $term.Length
        })
    }
}

$result = [pscustomobject]@{
    status = if ($issues.Count -eq 0) { 'PASS' } else { 'FAIL' }
    issue_count = $issues.Count
    issues = @($issues)
    warning_count = $warnings.Count
    warnings = @($warnings)
}

$result | ConvertTo-Json -Depth 6
if ($issues.Count -gt 0) {
    exit 1
}
exit 0
