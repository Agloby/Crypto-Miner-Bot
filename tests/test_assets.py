import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AssetTests(unittest.TestCase):
    def test_config_example_is_valid_and_has_no_secrets(self):
        text = (ROOT / "config" / "config.example.json").read_text(encoding="utf-8")
        config = json.loads(text)
        self.assertEqual(config["max_gpu_temp_c"], 78)
        self.assertEqual(config["resume_gpu_temp_c"], 70)
        lowered = text.lower()
        for forbidden in ("seed phrase", "private_key", "api_secret", "cookie"):
            self.assertNotIn(forbidden, lowered)

    def test_dashboard_javascript_syntax(self):
        node = os.environ.get("CRYPTO_MINER_NODE") or shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for the dashboard syntax test")
        html = (ROOT / "dashboard" / "AI_Passive_Income_Dashboard_Crypto_AutoProfit.html").read_text(encoding="utf-8")
        start, end = html.find("<script>"), html.rfind("</script>")
        self.assertGreaterEqual(start, 0)
        self.assertGreater(end, start)
        script = html[start + len("<script>"):end]
        with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
            handle.write(script)
            path = Path(handle.name)
        try:
            result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            path.unlink(missing_ok=True)

    def test_powershell_launcher_syntax(self):
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        self.assertIsNotNone(powershell, "Windows PowerShell is required for launcher syntax testing")
        launcher = ROOT / "launcher" / "ONE_CLICK_START.ps1"
        quoted = str(launcher).replace("'", "''")
        command = f"$e=$null; [System.Management.Automation.Language.Parser]::ParseFile('{quoted}',[ref]$null,[ref]$e)|Out-Null; if($e.Count){{$e|ForEach-Object{{$_.Message}};exit 1}}"
        result = subprocess.run([powershell, "-NoProfile", "-Command", command], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_healthy_bridge_reuse_contract(self):
        text = (ROOT / "launcher" / "ONE_CLICK_START.ps1").read_text(encoding="utf-8")
        self.assertIn("$bridgeHealth.project_id -eq $ProjectId", text)
        self.assertIn("healthy project bridge reused", text)

    def test_stale_bridge_is_targeted_and_unrelated_owner_is_preserved(self):
        text = (ROOT / "launcher" / "ONE_CLICK_START.ps1").read_text(encoding="utf-8")
        self.assertIn("$commandLine -like \"*$BridgePath*\"", text)
        self.assertIn("it was not terminated", text)
        self.assertNotIn("Get-Process python | Stop-Process", text)

    def test_root_batch_file_points_to_launcher(self):
        text = (ROOT / "START_EVERYTHING.bat").read_text(encoding="utf-8").lower()
        self.assertIn("launcher\\one_click_start.ps1", text)


if __name__ == "__main__":
    unittest.main()

