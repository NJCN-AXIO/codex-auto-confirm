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

function Read-VisibleSnapshots {
    $items = @()
    $windows = $root.FindAll(
        [System.Windows.Automation.TreeScope]::Children,
        $trueCondition
    )
    foreach ($window in $windows) {
        if ($window.Current.ClassName -ne "CASCADIA_HOSTING_WINDOW_CLASS") {
            continue
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
                foreach ($range in $pattern.GetVisibleRanges()) {
                    $parts += $range.GetText(-1)
                }
                $items += [pscustomobject]@{
                    class = [string]$window.Current.ClassName
                    hwnd = [int]$window.Current.NativeWindowHandle
                    title = [string]$window.Current.Name
                    process_id = [int]$window.Current.ProcessId
                    input_ambiguous = [bool]$inputAmbiguous
                    text = ($parts -join [Environment]::NewLine)
                }
            } catch {
                continue
            }
        }
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
