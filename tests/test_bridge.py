import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("crypto_bridge", ROOT / "bridge" / "crypto_bridge.py")
bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = bridge
SPEC.loader.exec_module(bridge)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        bridge.STATE.managed_process = None
        bridge.STATE.desired_mining = False
        bridge.STATE.thermal_stopped = False
        bridge.STATE.transition = None
        bridge.STATE.last_error = None
        bridge.STATE.status_cache = None
        bridge.STATE.status_cache_time = 0

    def test_config_json_without_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('{"value": 1}', encoding="utf-8")
            self.assertEqual(bridge.load_json(path, {}), {"value": 1})

    def test_config_json_with_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('\ufeff{"value": 2}', encoding="utf-8")
            self.assertEqual(bridge.load_json(path, {}), {"value": 2})

    def test_save_json_is_bom_free(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "runtime.json"
            bridge.save_json(path, {"path": r"C:\NiceHash\miner.exe"})
            self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["path"], r"C:\NiceHash\miner.exe")

    def test_configured_miner_path_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            miner = Path(folder) / "NiceHashQuickMiner.exe"
            miner.touch()
            result = bridge.detect_miner_path({"miner_path": str(miner)}, candidates=[(miner, "configured")], search_roots=[])
            self.assertTrue(result["detected"])
            self.assertEqual(result["method"], "configured")

    def test_configured_miner_path_missing_is_reported(self):
        missing = Path(tempfile.gettempdir()) / "does-not-exist" / "NiceHashQuickMiner.exe"
        result = bridge.detect_miner_path({"miner_path": str(missing)}, candidates=[(missing, "configured")], search_roots=[])
        self.assertFalse(result["detected"])
        self.assertIn("Configured miner path does not exist", result["error"])

    def test_fallback_miner_detection(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.exe"
            fallback = Path(folder) / "NiceHashQuickMiner.exe"
            fallback.touch()
            result = bridge.detect_miner_path({}, candidates=[(missing, "configured"), (fallback, "common_location")], search_roots=[])
            self.assertTrue(result["detected"])
            self.assertEqual(result["path"], str(fallback))

    def test_confirmed_quickminer_path_detection(self):
        with tempfile.TemporaryDirectory() as folder:
            known = Path(folder) / "NiceHashQuickMiner.exe"
            known.touch()
            result = bridge.detect_miner_path({}, candidates=[(known, "confirmed_path")], search_roots=[])
            self.assertEqual(result["method"], "confirmed_path")

    @mock.patch.object(bridge, "nvidia_telemetry", return_value={"name": "GPU", "temperature_c": 50, "power_w": 100, "utilization_pct": 10})
    @mock.patch.object(bridge, "config", return_value={"max_gpu_temp_c": 78, "minimum_profit_eur_per_day": 0})
    @mock.patch.object(bridge, "quickminer_process_running", return_value=True)
    @mock.patch.object(bridge.subprocess, "Popen")
    def test_no_duplicate_quickminer_start(self, popen, _running, _config, _gpu):
        ok, result = bridge.start_mining()
        self.assertTrue(ok)
        self.assertEqual(result["code"], "ALREADY_RUNNING")
        popen.assert_not_called()

    @mock.patch.object(bridge, "nvidia_telemetry", return_value={"name": "GPU", "temperature_c": 50, "power_w": 100, "utilization_pct": 10})
    @mock.patch.object(bridge, "config", return_value={"max_gpu_temp_c": 78, "minimum_profit_eur_per_day": 0})
    @mock.patch.object(bridge, "quickminer_process_running", return_value=False)
    @mock.patch.object(bridge, "is_admin", return_value=True)
    @mock.patch.object(bridge, "detect_miner_path", return_value={"detected": True, "path": r"C:\miner.exe", "method": "configured", "error": None})
    def test_winerror_740_is_structured(self, _detect, _admin, _running, _config, _gpu):
        error = OSError("elevation")
        error.winerror = 740
        with mock.patch.object(bridge.subprocess, "Popen", side_effect=error):
            ok, result = bridge.start_mining()
        self.assertFalse(ok)
        self.assertEqual(result["code"], "ADMIN_REQUIRED")
        self.assertIn("elevation", result["message"])

    def test_health_is_lightweight(self):
        server = bridge.QuietThreadingHTTPServer(("127.0.0.1", 0), bridge.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.object(bridge, "status", side_effect=AssertionError("health called status")), mock.patch.object(bridge, "preflight", side_effect=AssertionError("health called preflight")):
                payload = json.loads(urlopen(f"http://127.0.0.1:{server.server_port}/api/crypto/health", timeout=2).read())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["project_id"], bridge.PROJECT_ID)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_status_does_not_run_preflight(self):
        expected = {"mining_state": "IDLE"}
        with mock.patch.object(bridge, "preflight", side_effect=AssertionError("called")), mock.patch.object(bridge, "_live_status", return_value=expected):
            self.assertEqual(bridge.status(force=True), expected)

    def test_browser_abort_does_not_escape(self):
        class BrokenWriter:
            def write(self, _body):
                raise BrokenPipeError()
        class FakeHandler:
            wfile = BrokenWriter()
            def send_response(self, _status): pass
            def send_header(self, *_args): pass
            def end_headers(self): pass
            def _cors(self): pass
        bridge.Handler._json(FakeHandler(), {"ok": True})

    def test_process_running_is_not_gpu_mining(self):
        gpu = {"name": "GPU", "temperature_c": 55, "power_w": 90, "utilization_pct": 30}
        bridge.STATE.desired_mining = True
        with mock.patch.object(bridge, "config", return_value={}), mock.patch.object(bridge, "nvidia_telemetry", return_value=gpu), mock.patch.object(bridge, "quickminer_process_running", return_value=True), mock.patch.object(bridge, "excavator_process_running", return_value=True), mock.patch.object(bridge, "excavator_status", return_value={"api_reachable": True, "hashrate": None, "gpu_disabled": False, "error": None}):
            result = bridge._live_status()
        self.assertFalse(result["gpu_mining"])
        self.assertEqual(result["mining_state"], "STARTING")

    def test_positive_excavator_hashrate_is_mining(self):
        gpu = {"name": "GPU", "temperature_c": 55, "power_w": 150, "utilization_pct": 95}
        bridge.STATE.transition = "STARTING"
        with mock.patch.object(bridge, "config", return_value={}), mock.patch.object(bridge, "nvidia_telemetry", return_value=gpu), mock.patch.object(bridge, "quickminer_process_running", return_value=True), mock.patch.object(bridge, "excavator_process_running", return_value=True), mock.patch.object(bridge, "excavator_status", return_value={"api_reachable": True, "hashrate": 42.5, "gpu_disabled": False, "error": None}):
            result = bridge._live_status()
        self.assertTrue(result["gpu_mining"])
        self.assertEqual(result["mining_state"], "MINING")
        self.assertIsNone(bridge.STATE.transition)

    def test_excavator_hashrate_does_not_double_count_rpc_views(self):
        def rpc(_method):
            return {"result": {"workers": [{"speed": 10.0}]}}
        result = bridge.excavator_status(rpc)
        self.assertEqual(result["hashrate"], 10.0)

    def test_disabled_gpu_never_reports_mining(self):
        gpu = {"name": "GPU", "temperature_c": 55, "power_w": 90, "utilization_pct": 10}
        with mock.patch.object(bridge, "config", return_value={}), mock.patch.object(bridge, "nvidia_telemetry", return_value=gpu), mock.patch.object(bridge, "quickminer_process_running", return_value=True), mock.patch.object(bridge, "excavator_process_running", return_value=True), mock.patch.object(bridge, "excavator_status", return_value={"api_reachable": True, "hashrate": 42.5, "gpu_disabled": True, "error": None}):
            result = bridge._live_status()
        self.assertFalse(result["gpu_mining"])
        self.assertTrue(result["gpu_disabled"])

    def test_thermal_stop_and_resume_logic(self):
        cfg = {"max_gpu_temp_c": 78, "resume_gpu_temp_c": 70, "auto_resume_after_thermal_stop": True}
        self.assertEqual(bridge.thermal_action({"gpu_temperature": 78, "gpu_mining": True}, cfg, False), "stop")
        self.assertEqual(bridge.thermal_action({"gpu_temperature": 70, "gpu_mining": False}, cfg, True), "resume")
        self.assertIsNone(bridge.thermal_action({"gpu_temperature": 74, "gpu_mining": False}, cfg, True))

    def test_ignore_electricity_cost_logic(self):
        gpu = {"power_w": 200}
        ignored = bridge.compute_profitability({"gross_revenue_eur_per_day": 2, "electricity_eur_per_kwh": 0.5, "ignore_electricity_cost": True}, gpu)
        included = bridge.compute_profitability({"gross_revenue_eur_per_day": 2, "electricity_eur_per_kwh": 0.5, "ignore_electricity_cost": False}, gpu)
        self.assertEqual(ignored["decision_profit_per_day"], 2)
        self.assertAlmostEqual(included["electricity_cost_per_day"], 2.4)
        self.assertAlmostEqual(included["decision_profit_per_day"], -0.4)

    def test_unknown_profitability_is_not_zero(self):
        result = bridge.compute_profitability({}, {"power_w": 100})
        self.assertIsNone(result["gross_revenue_per_day"])
        self.assertIsNone(result["decision_profit_per_day"])
        self.assertEqual(result["decision"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()

