from pathlib import Path
import unittest


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


class ServerScriptTests(unittest.TestCase):
    def test_package_server_bat_exists_and_calls_tools_script(self):
        batch_path = WORKSPACE_ROOT / "package_pywrapper_server.bat"

        self.assertTrue(batch_path.exists(), batch_path)
        text = batch_path.read_text(encoding="utf-8")
        self.assertIn(r"tools\package_pywrapper_server.ps1", text)
        self.assertIn("powershell -NoProfile -ExecutionPolicy Bypass -File", text)

    def test_close_server_bat_exists_and_targets_server_port_and_process_name(self):
        batch_path = WORKSPACE_ROOT / "closeserver.bat"

        self.assertTrue(batch_path.exists(), batch_path)
        text = batch_path.read_text(encoding="utf-8")
        self.assertIn("Get-NetTCPConnection", text)
        self.assertIn("30415", text)
        self.assertIn("ocrapp_pureray", text)
        self.assertIn("Get-Process", text)
        self.assertNotIn("foreach ($pid", text)
        self.assertIn("foreach ($targetPid", text)

    def test_restart_server_bat_exists_and_calls_tools_script(self):
        batch_path = WORKSPACE_ROOT / "restart_server.bat"

        self.assertTrue(batch_path.exists(), batch_path)
        text = batch_path.read_text(encoding="utf-8")
        self.assertIn(r"tools\restart_server.ps1", text)
        self.assertIn("powershell -NoProfile -ExecutionPolicy Bypass -File", text)

    def test_restart_server_powershell_targets_current_server_and_stop_script(self):
        script_path = WORKSPACE_ROOT / "tools" / "restart_server.ps1"

        self.assertTrue(script_path.exists(), script_path)
        text = script_path.read_text(encoding="utf-8")
        self.assertIn(r"closeserver.bat", text)
        self.assertIn(r"dist\OCRSERVER\ocrapp_pureray.exe", text)
        self.assertIn("Start-Process", text)
        self.assertIn("Test-Path", text)

    def test_package_script_copies_settings_into_output_root(self):
        script_path = WORKSPACE_ROOT / "tools" / "package_pywrapper_server.ps1"

        self.assertTrue(script_path.exists(), script_path)
        text = script_path.read_text(encoding="utf-8")
        self.assertIn('Join-Path $distDir "settings"', text)
        self.assertIn("Copy-Item -LiteralPath $settingsPath", text)

    def test_package_script_copies_release_files_into_ocrserver(self):
        script_path = WORKSPACE_ROOT / "tools" / "package_pywrapper_server.ps1"

        self.assertTrue(script_path.exists(), script_path)
        text = script_path.read_text(encoding="utf-8")
        self.assertIn('Join-Path $packageRoot "closeserver.bat"', text)
        self.assertIn('Join-Path $packageRoot "restart_server.bat"', text)
        self.assertIn('Join-Path $packageRoot "test_ocr_client.exe"', text)
        self.assertIn("$compatDistDir", text)

    def test_publish_release_bat_exists_and_calls_tools_script(self):
        batch_path = WORKSPACE_ROOT / "publish_release.bat"

        self.assertTrue(batch_path.exists(), batch_path)
        text = batch_path.read_text(encoding="utf-8")
        self.assertIn(r"tools\publish_release.ps1", text)
        self.assertIn("powershell -NoProfile -ExecutionPolicy Bypass -File", text)

    def test_publish_release_powershell_targets_va_repo_and_git_push(self):
        script_path = WORKSPACE_ROOT / "tools" / "publish_release.ps1"

        self.assertTrue(script_path.exists(), script_path)
        text = script_path.read_text(encoding="utf-8")
        self.assertIn(r"D:\ocr3\VA", text)
        self.assertIn(r"package_pywrapper_server.bat", text)
        self.assertIn("git -C", text)
        self.assertIn("status --porcelain", text)
        self.assertIn("Remove-Item", text)
        self.assertIn(".git", text)
        self.assertIn("push -u origin HEAD:main", text)

    def test_publish_release_stops_running_server_before_packaging(self):
        script_path = WORKSPACE_ROOT / "tools" / "publish_release.ps1"

        self.assertTrue(script_path.exists(), script_path)
        text = script_path.read_text(encoding="utf-8")
        stop_assignment = '$stopScript = Join-Path $packageRoot "closeserver.bat"'
        package_call = "& $packageScript"
        stop_call = "& $stopScript"
        self.assertIn(stop_assignment, text)
        self.assertIn(stop_call, text)
        self.assertLess(text.index(stop_call), text.index(package_call))
        self.assertIn("Stop script failed with exit code", text)


if __name__ == "__main__":
    unittest.main()
