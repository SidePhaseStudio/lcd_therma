"""Read-only Linux sampler, sent over SSH to the VPS's Python interpreter."""

import glob
import json
import os
from pathlib import Path
import shutil
import socket
import time


def read_snapshot(interface):
    cpu = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
    for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
        name, values = line.split(":", 1)
        if name.strip() == interface:
            fields = values.split()
            return cpu, (int(fields[0]), int(fields[8]))
    raise RuntimeError("VPS network interface missing")


def collect_metrics():
    routes = [line.split() for line in Path("/proc/net/route").read_text().splitlines()[1:]]
    interface = next(row[0] for row in routes if row[1] == "00000000" and int(row[3], 16) & 1)
    previous_cpu, previous_net = read_snapshot(interface)
    start = time.monotonic()
    time.sleep(1)
    cpu, net = read_snapshot(interface)
    elapsed = time.monotonic() - start
    total_delta = sum(cpu) - sum(previous_cpu)
    idle_delta = cpu[3] + cpu[4] - previous_cpu[3] - previous_cpu[4]
    cpu_percent = max(0, min(100, 100 * (total_delta - idle_delta) / max(total_delta, 1)))

    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.split()[0])
    mem_percent = 100 * (memory["MemTotal"] - memory["MemAvailable"]) / memory["MemTotal"]
    swap_percent = 100 * (memory["SwapTotal"] - memory["SwapFree"]) / memory["SwapTotal"] if memory["SwapTotal"] else 0
    disk = shutil.disk_usage("/")
    uptime_s = int(float(Path("/proc/uptime").read_text().split()[0]))
    days, rem = divmod(uptime_s, 86400)
    hours, rem = divmod(rem, 3600)
    uptime = f"{days}d {hours}h" if days else f"{hours}h {rem // 60}m"

    temp = "--"
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            temp = f"{float(Path(path).read_text()) / 1000:.1f}C"
            break
        except (OSError, ValueError):
            continue

    ping = "Timeout"
    try:
        started = time.monotonic()
        with socket.create_connection(("8.8.8.8", 443), timeout=2):
            ping = f"{(time.monotonic() - started) * 1000:.0f}ms"
    except OSError:
        pass

    return {
        "cpu": f"{cpu_percent:.0f}%", "load": f"{os.getloadavg()[0]:.2f}",
        "mem": f"{mem_percent:.0f}%", "swap": f"{swap_percent:.0f}%",
        "disk": f"{disk.used / disk.total * 100:.0f}%", "temp": temp,
        "uptime": uptime, "ping": ping,
        "rx": f"{max(0, net[0] - previous_net[0]) * 8 / elapsed / 1_000_000:.1f}",
        "tx": f"{max(0, net[1] - previous_net[1]) * 8 / elapsed / 1_000_000:.1f}",
    }


if __name__ == "__main__":
    print(json.dumps(collect_metrics()))
