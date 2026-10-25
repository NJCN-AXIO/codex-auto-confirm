$ErrorActionPreference = "Stop"
# Hidden launches can inherit the OEM codec, which replaces Codex's prompt and
# status glyphs with '?'. The Python reader uses UTF-8 for this pipe protocol.
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$root = [System.Windows.Automation.AutomationElement]::RootElement
$trueCondition = [System.Windows.Automation.Condition]::TrueCondition
$termCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ClassNameProperty,
    "TermControl"
)
$script:revealedApprovalWindows = @{}
$script:viewportDiagnostics = @{}
$approvalTitle = $env:CODEX_AUTO_CONFIRM_ACTION_TITLE
if (-not $approvalTitle) { $approvalTitle = 'Action Required' }

function Restore-ApprovalViewport($window, $pattern, $ranges, $inputAmbiguous, $visibleText) {
    $hwnd = [int]$window.Current.NativeWindowHandle
    $diagnostic = [ordered]@{reason='not_requested'; attempts=0; tail_chars=0}
    $script:viewportDiagnostics[$hwnd] = $diagnostic
    if ($script:revealedApprovalWindows.ContainsKey($hwnd)) {
        $diagnostic.attempts = $script:revealedApprovalWindows[$hwnd].attempts
    }
    if ($window.Current.Name.IndexOf($approvalTitle, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        $script:revealedApprovalWindows.Remove($hwnd)
        return $false
    }
    if ($inputAmbiguous) { $diagnostic.reason='input_ambiguous'; return $false }
    if ($ranges.Count -eq 0) { $diagnostic.reason='visible_range_missing'; return $false }
    # This is a view repair only. Never return DocumentRange text as evidence
    # for Enter or recovery; a later independent scan must read the real menu.
    try {
        $footer = 'Press enter to confirm or esc to cancel'
        $selectionPattern = '(?im)^\s*[\u203a\u00bb>]\s*\d+[.)]\s+(?<option>[^\r\n]+)'
        if ($visibleText.TrimEnd().EndsWith($footer, [StringComparison]::OrdinalIgnoreCase) -and
            [regex]::IsMatch($visibleText, $selectionPattern)) { $diagnostic.reason='visible_menu'; return $false }
        foreach ($selection in $pattern.GetSelection()) {
            if ($selection.GetText(-1).Length -gt 0) { $diagnostic.reason='text_selection'; return $false }
        }
        $endPoint = [System.Windows.Automation.Text.TextPatternRangeEndpoint]::End
        $document = $pattern.DocumentRange
        if ($ranges[-1].CompareEndpoints($endPoint, $document, $endPoint) -ge 0) {
            $diagnostic.reason='at_buffer_end_no_menu'; return $false
        }
        $tail = $document.Clone()
        $tail.MoveEndpointByRange([System.Windows.Automation.Text.TextPatternRangeEndpoint]::Start, $tail, $endPoint)
        $null = $tail.MoveEndpointByUnit([System.Windows.Automation.Text.TextPatternRangeEndpoint]::Start,
            [System.Windows.Automation.Text.TextUnit]::Character, -16000)
        $tailText = $tail.GetText(-1)
        $diagnostic.tail_chars=16000
        if (-not $tailText.TrimEnd().EndsWith($footer, [StringComparison]::OrdinalIgnoreCase)) {
            $diagnostic.reason='tail_no_current_menu'; return $false
        }
        $selected = [regex]::Matches($tailText, $selectionPattern)
        if ($selected.Count -eq 0) {
            $null = $tail.MoveEndpointByUnit([System.Windows.Automation.Text.TextPatternRangeEndpoint]::Start,
                [System.Windows.Automation.Text.TextUnit]::Character, -(65536-16000))
            $tailText = $tail.GetText(-1)
            $diagnostic.tail_chars=65536
            $selected = [regex]::Matches($tailText, $selectionPattern)
        }
        if ($selected.Count -eq 0) { $diagnostic.reason='tail_selected_out_of_bound'; return $false }
        $last = $selected[$selected.Count - 1]
        if ($last.Groups['option'].Value.Trim() -notmatch '^(?i:yes, proceed|yes, just this once|allow once|\u5141\u8bb8\u4e00\u6b21)(?:\s+\(y\))?$') {
            $diagnostic.reason='selected_option_not_once'; return $false
        }
        if ([regex]::IsMatch($tailText.Substring($last.Index + $last.Length), '(?m)^\s*[\u203a\u00bb>]')) {
            $diagnostic.reason='later_composer'; return $false
        }
        if (-not $script:revealedApprovalWindows.ContainsKey($hwnd)) {
            $script:revealedApprovalWindows[$hwnd] = @{attempts=0; next_at=[DateTime]::MinValue}
        }
        $episode = $script:revealedApprovalWindows[$hwnd]
        $now = (Get-Date).ToUniversalTime()
        $diagnostic.reason='viewport_retry_wait'
        if ($episode.attempts -ge 3) { $diagnostic.reason='viewport_exhausted' }
        elseif ($now -ge $episode.next_at) {
            # Consume each paced attempt before navigation, including failures.
            $episode.attempts++
            $delay = 1
            if ($episode.attempts -gt 1) { $delay=3 }
            $episode.next_at = $now.AddSeconds($delay)
            try {
                $tail.MoveEndpointByRange([System.Windows.Automation.Text.TextPatternRangeEndpoint]::Start, $tail, $endPoint)
                $tail.ScrollIntoView($false)
                $diagnostic.reason='viewport_revealed'
            } catch { $diagnostic.reason='viewport_navigation_failed' }
        }
        $diagnostic.attempts=$episode.attempts
        # A known historical viewport is unknown even if navigation failed.
        return $true
    } catch { $diagnostic.reason='viewport_provider_error'; return $false }
}

function Read-VisibleSnapshots {
    $items = @()
    $seenWindows = @{}
    $windows = $root.FindAll(
        [System.Windows.Automation.TreeScope]::Children,
        $trueCondition
    )
    foreach ($window in $windows) {
        if ($window.Current.ClassName -ne "CASCADIA_HOSTING_WINDOW_CLASS") {
            continue
        }
        $seenWindows[[int]$window.Current.NativeWindowHandle] = $true
        # Episode changes are authoritative even when TextPattern is missing.
        if ($window.Current.Name.IndexOf($approvalTitle, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            $script:revealedApprovalWindows.Remove([int]$window.Current.NativeWindowHandle)
        }
        try {
            $terms = $window.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                $termCondition
            )
            # Delivery targets the parent HWND, so multiple panes cannot be
            # safely associated with its one input target. Count every control,
            # including one whose text read later fails, and defer this window.
            $inputAmbiguous = $terms.Count -gt 1
        } catch {
            continue
        }
        foreach ($term in $terms) {
            try {
                $pattern = $null
                if (-not $term.TryGetCurrentPattern(
                    [System.Windows.Automation.TextPattern]::Pattern,
                    [ref]$pattern
                )) {
                    continue
                }
                $parts = @()
                $ranges = @($pattern.GetVisibleRanges())
                foreach ($range in $ranges) {
                    $parts += $range.GetText(-1)
                }
                $visibleText = ($parts -join [Environment]::NewLine)
                if (Restore-ApprovalViewport $window $pattern $ranges $inputAmbiguous $visibleText) {
                    $visibleText = ''
                }
                $items += [pscustomobject]@{
                    class = [string]$window.Current.ClassName
                    hwnd = [int]$window.Current.NativeWindowHandle
                    title = [string]$window.Current.Name
                    process_id = [int]$window.Current.ProcessId
                    input_ambiguous = [bool]$inputAmbiguous
                    text = $visibleText
                    viewport_repair = [pscustomobject]$script:viewportDiagnostics[[int]$window.Current.NativeWindowHandle]
                }
            } catch {
                continue
            }
        }
    }
    foreach ($hwnd in @($script:revealedApprovalWindows.Keys)) {
        if (-not $seenWindows.ContainsKey($hwnd)) { $script:revealedApprovalWindows.Remove($hwnd) }
    }
    foreach ($hwnd in @($script:viewportDiagnostics.Keys)) {
        if (-not $seenWindows.ContainsKey($hwnd)) { $script:viewportDiagnostics.Remove($hwnd) }
    }
    return $items
}

while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) {
        break
    }
    switch ($line.Trim().ToLowerInvariant()) {
        "scan" {
            $items = @(Read-VisibleSnapshots)
            if ($items.Count -eq 0) {
                [Console]::Out.WriteLine("[]")
            } else {
                [Console]::Out.WriteLine(
                    (ConvertTo-Json -InputObject ([object[]]$items) -Compress -Depth 5)
                )
            }
            [Console]::Out.Flush()
        }
        "quit" {
            break
        }
    }
}
