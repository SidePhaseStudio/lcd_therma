import json
import threading
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

    with patch.object(vps, "collect_metrics", side_effect=[metrics, metrics, KeyboardInterrupt]), \
            patch.object(vps.time, "monotonic", side_effect=[0, 1, 5, 6, 10]), \
            patch.object(vps.time, "sleep") as sleep, patch("builtins.print") as output:
        try:
            vps.stream_metrics()
        except KeyboardInterrupt:
            pass
        assert output.call_count == 2
        assert all(call.kwargs == {"flush": True} for call in output.call_args_list)
        assert [call.args[0] for call in sleep.call_args_list] == [4, 4]

    stop = threading.Event()
    process = Mock()
    process.stdin.closed = True
    process.poll.return_value = None
    samples = [metrics, {**metrics, "cpu": "21%"}]

    def next_sample():
        sample = samples.pop(0)
        if not samples:
            stop.set()
        return json.dumps(sample) + "\n"

    process.stdout.readline.side_effect = next_sample
    with patch.object(lcd.subprocess, "Popen", return_value=process) as ssh, \
            patch.object(lcd.select, "select", return_value=([process.stdout], [], [])), \
            patch.dict(lcd._pending, {}, clear=True):
        lcd.stream_vps_metrics(stop)
        assert lcd._pending["vps"]["cpu"] == "21%"
        ssh.assert_called_once()
        assert ssh.call_args.args[0][-4:] == ["uk.sidephasestudio.com", "python3", "-u", "-"]
        assert "def stream_metrics" in process.stdin.write.call_args.args[0]
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=3)
        process.stdout.close.assert_called_once()

    for invalid in ([], {}, {**metrics, "cpu": 20}):
        stop = threading.Event()
        process = Mock()
        process.stdin.closed = True
        process.poll.return_value = 1
        process.stdout.readline.return_value = json.dumps(invalid) + "\n"
        with patch.object(lcd.subprocess, "Popen", return_value=process), \
                patch.object(lcd.select, "select", return_value=([process.stdout], [], [])), \
                patch.object(stop, "wait", return_value=True), \
                patch.dict(lcd._pending, {}, clear=True):
            lcd.stream_vps_metrics(stop)
            assert "vps" not in lcd._pending

    stop = threading.Event()
    disconnected = Mock()
    disconnected.stdin.closed = True
    disconnected.poll.return_value = 1
    disconnected.stdout.readline.return_value = ""
    recovered = Mock()
    recovered.stdin.closed = True
    recovered.poll.return_value = None

    def recovered_sample():
        stop.set()
        return json.dumps(metrics) + "\n"

    recovered.stdout.readline.side_effect = recovered_sample
    with patch.object(lcd.subprocess, "Popen", side_effect=[disconnected, recovered]) as ssh, \
            patch.object(lcd.select, "select", side_effect=lambda streams, *_: (streams, [], [])), \
            patch.object(stop, "wait", return_value=False), \
            patch.dict(lcd._pending, {}, clear=True):
        lcd.stream_vps_metrics(stop)
        assert ssh.call_count == 2
        assert lcd._pending["vps"] == metrics

    stalled = Mock()
    stalled.stdin.closed = True
    stalled.poll.return_value = None
    stalled.wait.side_effect = [lcd.subprocess.TimeoutExpired("ssh", 3), 0]
    with patch.object(lcd.subprocess, "Popen", return_value=stalled), \
            patch.object(lcd.select, "select", return_value=([], [], [])), \
            patch.object(lcd.time, "monotonic", side_effect=[0, 16]), \
            patch.object(threading.Event, "wait", return_value=True):
        lcd.stream_vps_metrics(threading.Event())
        stalled.terminate.assert_called_once()
        stalled.kill.assert_called_once()


if __name__ == "__main__":
    check()
    print("VPS metrics checks passed")
