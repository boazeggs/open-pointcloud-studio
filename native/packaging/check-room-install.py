"""Verify that an installed desktop opens and renders the pinned PCL room scan."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import tempfile
import time

gui = runpy.run_path(str(Path(__file__).with_name("gui-smoke.py")))
POINTS = 112586
SOURCE_SHA = "52c373a67d8beaa318b5e8c024f06e219f14acc1db28fa7333ff5dc73840428b"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("scan", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    scan = args.scan.resolve()
    assert hashlib.sha256(scan.read_bytes()).hexdigest() == SOURCE_SHA
    profile = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    environment = {**os.environ, "XDG_CONFIG_HOME": str(Path(profile.name)/"config"),
                   "XDG_CACHE_HOME": str(Path(profile.name)/"cache")}
    print("Starting the installed MCP server", flush=True)
    server = gui["Server"](str(args.binary), environment)
    window = None
    try:
        started = server.request("initialize", {"protocolVersion": "2025-11-25",
                                 "clientInfo": {"name": "installed-room-scan", "version": "1"}, "capabilities": {}})
        assert started["serverInfo"]["version"] == "2026.48.0"
        server.notify("notifications/initialized")
        print("Opening the scan in the desktop viewer", flush=True)
        window = server.tool("start_instance", files=[str(scan)])["started"]["pid"]
        for _ in range(120):
            clouds = server.tool("status")["result"]["clouds"]
            if len(clouds) == 1 and os.path.samefile(clouds[0]["path"], scan) and clouds[0]["points"] == POINTS:
                break
            time.sleep(.25)
        else:
            raise RuntimeError("Room scan did not open")
        print("Loaded", POINTS, "points", flush=True)
        server.tool("zoom_all")
        server.tool("set_point_size", size=3)
        images = []
        for visible in (True, False):
            server.tool("set_visible", index=0, visible=visible)
            assert server.tool("wait_until_idle", timeout_seconds=60)["idle"]
            path = (args.output / ("room.png" if visible else "hidden.png")).resolve()
            server.tool("screenshot", path=str(path), max_edge=1024)
            images.append(gui["read_png"](path))
        width, height, pixels = images[0]
        assert (width, height) == images[1][:2]
        changed = sum(a != b for a, b in zip(pixels, images[1][2]))
        assert changed > 1000, f"Only {changed} pixels changed with layer visibility"
        print(json.dumps({"product_version": started["serverInfo"]["version"], "source_sha256": SOURCE_SHA,
                          "points": POINTS, "viewport": [width, height], "changed_pixels": changed}), flush=True)
    finally:
        if window is not None:
            gui["end_process"](window)
        server.close()
        profile.cleanup()


if __name__ == "__main__":
    main()
