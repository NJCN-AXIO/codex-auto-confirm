"""A scrolled approval must be revealed before fresh visible text can authorize Enter."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.test_codex_auto_confirm_recovery import load_module


class ApprovalViewportTests(unittest.TestCase):
    def read_helper(self, *, title="Action Required | example-project", selected="", multiple=False,
                    fail=False, current=True, at_end=False, option="Yes, proceed (y)",
                    footer=True, reset_episode=False, remove_window=False, reset_unreadable=False,
                    fail_first=0, clock_steps=(0, 0), extra_clock=(), scope_chars=0):
        helper = str(Path(__file__).with_name("codex_terminal_uia_reader.ps1")).replace("'", "''")
        parameters = json.dumps(dict(title=title, selected=selected, multiple=multiple,
                                     fail=fail, current=current, at_end=at_end, option=option,
                                     footer=footer, reset_episode=reset_episode, remove_window=remove_window,
                                     reset_unreadable=reset_unreadable, fail_first=fail_first,
                                     clock_steps=clock_steps, extra_clock=extra_clock,
                                     scope_chars=scope_chars)).replace("'", "''")
        command = ". '" + helper + "'; $options = '" + parameters + "' | ConvertFrom-Json; " + r'''
            $script:scrolled = $false
            $script:scrolls = 0
            $script:clock_ms = 0
            function Get-Date { return [DateTime]::Parse('2026-10-25T00:00:00Z').AddMilliseconds($script:clock_ms) }
            $script:menu = "Would you like to run the following command?`n$ echo CHECK`n" +
                [char]0x203a + ' 1. ' + $options.option + "`n2. No, and tell Codex what to do differently (esc)`n"
            if ($options.scope_chars) {
                $script:menu = $script:menu.Replace("`n2. No,", "`n2. Yes, and don't ask again for commands that start with ``" +
                    ('x' * $options.scope_chars) + "```n3. No,")
            }
            if ($options.footer) { $script:menu += 'Press enter to confirm or esc to cancel' }
            $script:oldText = 'Old transcript output without a menu'
            $script:tail = $script:menu
            $script:tailLimit = 0
            if (-not $options.current) { $script:tail += "`nWorking (2s)" }
            $visible = [pscustomobject]@{}
            $visible | Add-Member ScriptMethod GetText {
                if ($script:scrolled -or $options.at_end) { return $script:menu }
                return $script:oldText
            }
            $visible | Add-Member ScriptMethod CompareEndpoints {
                if ($script:scrolled -or $options.at_end) { return 0 }
                return -1
            }
            $doc = [pscustomobject]@{}
            $doc | Add-Member ScriptMethod Clone { return $this }
            $doc | Add-Member ScriptMethod GetText {
                if ($script:tailLimit -gt 0) { return $script:tail.Substring([Math]::Max(0,$script:tail.Length-$script:tailLimit)) }
                return $script:tail
            }
            $doc | Add-Member ScriptMethod MoveEndpointByRange { $script:tailLimit=0 }
            $doc | Add-Member ScriptMethod MoveEndpointByUnit { $script:tailLimit += [Math]::Abs($args[2]); return $args[2] }
            $doc | Add-Member ScriptMethod ScrollIntoView {
                $script:scrolls++
                if ($options.fail -or $script:scrolls -le $options.fail_first) { throw 'provider refused navigation' }
                $script:scrolled = $true
            }
            $selection = [pscustomobject]@{}
            $selection | Add-Member ScriptMethod GetText { return $options.selected }
            $pattern = [pscustomobject]@{ Ranges=@($visible); DocumentRange=$doc; Selection=$selection }
            $pattern | Add-Member ScriptMethod GetVisibleRanges { return $this.Ranges }
            $pattern | Add-Member ScriptMethod GetSelection { return @($this.Selection) }
            $term = [pscustomobject]@{ Pattern=$pattern }
            $term | Add-Member ScriptMethod TryGetCurrentPattern { $args[1].Value=$this.Pattern; return $true }
            $window = [pscustomobject]@{
                Current=[pscustomobject]@{ClassName='CASCADIA_HOSTING_WINDOW_CLASS';
                    NativeWindowHandle=901; Name=$options.title; ProcessId=123}
                Results=@($term)
            }
            if ($options.multiple) { $window.Results=@($term,$term) }
            $window | Add-Member ScriptMethod FindAll { return $this.Results }
            $root = [pscustomobject]@{ Results=@($window) }
            $root | Add-Member ScriptMethod FindAll { return $this.Results }
            $first=@(Read-VisibleSnapshots)
            if ($options.reset_episode -or $options.reset_unreadable) {
                $window.Current.Name='Codex'
                $saved=$window.Results
                if ($options.reset_unreadable) { $window.Results=@() }
                $null=@(Read-VisibleSnapshots)
                $window.Results=$saved
                $window.Current.Name=$options.title
            }
            if ($options.remove_window) {
                $root.Results=@()
                $null=@(Read-VisibleSnapshots)
                $root.Results=@($window)
            }
            $script:clock_ms = $options.clock_steps[0]
            $second=@(Read-VisibleSnapshots)
            $script:clock_ms = $options.clock_steps[1]
            $third=@(Read-VisibleSnapshots)
            $last=$third
            foreach ($clock in $options.extra_clock) {
                $script:clock_ms=$clock
                $last=@(Read-VisibleSnapshots)
            }
            @{first=$first; second=$second; third=$third; last=$last; scrolls=$script:scrolls} |
                ConvertTo-Json -Compress -Depth 5
        '''
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", command], input=b"quit\n", capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return json.loads(result.stdout.decode("utf-8"))

    def test_scrolled_menu_requires_a_new_visible_read_before_enter(self):
        payload = self.read_helper()
        self.assertEqual(payload["scrolls"], 1)
        self.assertEqual(payload["first"][0]["text"], "")
        self.assertIn("Yes, proceed", payload["second"][0]["text"])
        module, sender, trackers = load_module(), Mock(return_value=True), {}
        with patch.object(module, "recovery_input_busy", return_value=False):
            self.assertEqual(module.process_codex_approval_snapshots_multi(payload["first"], trackers, sender), [])
            self.assertEqual(module.process_codex_approval_snapshots_multi(payload["second"], trackers, sender), [(901, True)])
            self.assertEqual(module.process_codex_approval_snapshots_multi(payload["third"], trackers, sender), [])
        sender.assert_called_once_with(901)

    def test_current_viewport_does_not_need_navigation(self):
        payload = self.read_helper(at_end=True)
        self.assertEqual(payload["scrolls"], 0)
        self.assertIn("Yes, proceed", payload["first"][0]["text"])

    def test_navigation_failure_is_unknown_and_does_not_loop(self):
        payload = self.read_helper(fail=True)
        self.assertEqual(payload["scrolls"], 1)
        self.assertTrue(all(not payload[key][0]["text"] for key in ("first", "second", "third")))

    def test_nonapproval_history_selection_and_multiple_panes_do_not_scroll(self):
        for options in (dict(title="Codex"), dict(selected="user selected text"),
                        dict(multiple=True), dict(current=False), dict(footer=False),
                        dict(option="No, and tell Codex what to do differently (esc)"),
                        dict(option="Yes, and don't ask again for this command")):
            with self.subTest(options=options):
                payload = self.read_helper(**options)
                self.assertEqual(payload["scrolls"], 0)
                self.assertEqual(payload["first"][0]["text"], "Old transcript output without a menu")

    def test_a_later_episode_or_reopened_window_can_reveal_again(self):
        for options in (dict(reset_episode=True), dict(remove_window=True)):
            with self.subTest(options=options):
                payload = self.read_helper(fail=True, **options)
                self.assertEqual(payload["scrolls"], 2)

    def test_nonapproval_title_rearms_even_when_terminal_is_unreadable(self):
        payload = self.read_helper(fail=True, reset_unreadable=True)
        self.assertEqual(payload["scrolls"], 2)

    def test_one_transient_navigation_failure_can_recover_after_backoff(self):
        payload = self.read_helper(fail_first=1, clock_steps=(1100, 1400))
        self.assertEqual(payload["scrolls"], 2)
        self.assertEqual(payload["second"][0]["text"], "")
        self.assertIn("Yes, proceed", payload["third"][0]["text"])

    def test_navigation_retry_is_paced_and_stops_after_three_attempts(self):
        payload = self.read_helper(fail=True, clock_steps=(1100, 4200), extra_clock=(8000, 12000))
        self.assertEqual(payload["scrolls"], 3)
        self.assertEqual(payload["last"][0]["viewport_repair"]["reason"], "viewport_exhausted")

    def test_long_scope_tail_can_reveal_without_using_tail_as_authorization(self):
        payload = self.read_helper(scope_chars=20000)
        self.assertEqual(payload["scrolls"], 1)
        self.assertEqual(payload["first"][0]["text"], "")
        self.assertEqual(payload["first"][0]["viewport_repair"]["tail_chars"], 65536)


if __name__ == "__main__":
    unittest.main()
