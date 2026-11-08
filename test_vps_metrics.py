import json
from unittest.mock import Mock, patch

import lcd_therma_stats as lcd
import vps_metrics as vps


def check():
    files = {
        "/proc/net/route": "Iface Destination Gateway Flags\neth0 00000000 0100000A 0003\n",
        "/proc/meminfo": "MemTotal: 1000 kB\nMemAvailable: 250 kB\nSwapTotal: 500 kB\nSwapFree: 400 kB\n",
        "/proc/uptime": "90061.0 100000.0",
    }
    snapshots = [([100, 0, 0, 900, 0, 0, 0, 0], (1000, 2000)),
                 ([120, 0, 0, 980, 0, 0, 0, 0], (126000, 252000))]
    with patch.object(vps.Path, "read_text", autospec=True, side_effect=lambda path: files[str(path)]), \
            patch.object(vps, "read_snapshot", side_effect=snapshots), \
            patch.object(vps.time, "sleep"), \
            patch.object(vps.time, "monotonic", side_effect=[10, 11, 12, 12.003]), \
            patch.object(vps.shutil, "disk_usage", return_value=Mock(total=1000, used=250)), \
            patch.object(vps.os, "getloadavg", return_value=(0.42, 0, 0)), \
            patch.object(vps.glob, "glob", return_value=[]), \
            patch.object(vps.socket, "create_connection") as connect:
        metrics = vps.collect_metrics()
    assert metrics == {"cpu": "20%", "load": "0.42", "mem": "75%", "swap": "20%",
                       "disk": "25%", "temp": "--", "uptime": "1d 1h", "ping": "3ms",
                       "rx": "1.0", "tx": "2.0"}
    connect.assert_called_once_with(("8.8.8.8", 443), timeout=2)

    with patch.object(lcd.subprocess, "run", return_value=Mock(stdout=json.dumps(metrics))) as ssh:
        assert lcd.fetch_vps_metrics() == metrics
        assert ssh.call_args.args[0][-3:] == ["uk.sidephasestudio.com", "python3", "-"]
        assert "def collect_metrics" in ssh.call_args.kwargs["input"]
        for invalid in ([], {}, {**metrics, "cpu": 20}):
            ssh.return_value.stdout = json.dumps(invalid)
            assert lcd.fetch_vps_metrics() is None
        ssh.side_effect = lcd.subprocess.TimeoutExpired("ssh", 8)
        assert lcd.fetch_vps_metrics() is None


if __name__ == "__main__":
    check()
    print("VPS metrics checks passed")
