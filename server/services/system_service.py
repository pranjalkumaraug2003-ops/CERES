"""
system_service.py — Real-time system metrics via psutil
Feeds the left panel in the JARVIS UI via /ws/stats
"""
import asyncio
import psutil
from typing import Optional

def _get_cpu_temp() -> Optional[float]:
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for key in ('coretemp', 'cpu_thermal', 'k10temp', 'acpitz'):
                if key in temps:
                    return temps[key][0].current
    except Exception:
        pass
    return None

def _get_network_speed() -> float:
    """Return approximate current network speed in Mbps (sampled over 0.1s)."""
    try:
        io1 = psutil.net_io_counters()
        import time; time.sleep(0.1)
        io2 = psutil.net_io_counters()
        bytes_per_sec = (io2.bytes_sent + io2.bytes_recv - io1.bytes_sent - io1.bytes_recv) / 0.1
        return round(bytes_per_sec / 1_000_000 * 8, 2)  # Convert to Mbps
    except Exception:
        return 0.0

async def get_system_stats() -> dict:
    """Collect all system stats asynchronously."""
    loop = asyncio.get_event_loop()

    def _collect():
        mem = psutil.virtual_memory()
        battery = psutil.sensors_battery()
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "ram_used_gb": round(mem.used / 1e9, 1),
            "ram_total_gb": round(mem.total / 1e9, 1),
            "battery_percent": round(battery.percent if battery else 100, 1),
            "battery_plugged": battery.power_plugged if battery else True,
            "network_mbps": _get_network_speed(),
            "disk_used_gb": round(psutil.disk_usage('/').used / 1e9, 1),
            "disk_total_gb": round(psutil.disk_usage('/').total / 1e9, 1),
            "cpu_temp": _get_cpu_temp(),
        }

    return await loop.run_in_executor(None, _collect)
