"""Click Distance and two photo points, then verify both visible pane interiors.

Run in a fresh Xvfb X11 session at 1800x1000 and scale 1, with xdotool and
Pillow installed. Both windows and pointer input belong to this test display.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import time

from PIL import Image, ImageChops


REGIONS = {"model": (305, 220, 790, 859), "photo": (810, 220, 1290, 859)}


def pointer(*arguments):
    return subprocess.check_output(["xdotool", *map(str, arguments)], text=True, timeout=30).strip()


def click(x, y):
    pointer("mousemove", x, y, "sleep", ".12", "click", 1)


def wait_for(read, ready):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        value = read()
        if ready(value):
            return value
        time.sleep(.15)
    raise AssertionError(f"State did not settle. Last observation: {value}")


def fixture(directory):
    points = set()
    scan = directory / "room.xyz"
    with scan.open("x") as stream:
        for i in range(-50, 51):
            for j in range(-35, 36):
                offset, height = i / 10, j / 10
                for x, y in [(5, offset), (-5, offset), (offset, 5), (offset, -5)]:
                    print(x, y, height, 230, 150, 85, file=stream)
                    points.add((x, y, height))
    panorama = directory / "panorama.png"
    Image.new("RGB", (512, 256), (35, 78, 114)).save(panorama)
    return points, scan, panorama


def changed_pixels(left, right, bounds):
    diff = ImageChops.difference(left.crop(bounds), right.crop(bounds))
    return sum(max(pixel) > 10 for pixel in diff.getdata())


def exercise(server, directory, output, gui, binary, env):
    originals, scan, panorama = fixture(directory)
    digest = hashlib.sha256(scan.read_bytes()).hexdigest()
    tool = server.tool
    init = server.request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                          "clientInfo": {"name": "photo-measure", "version": "1"}})
    server.notify("notifications/initialized")
    try:
        pid = tool("start_instance", files=[str(scan)])["started"]["pid"]
    except gui["Failure"]:
        # The launcher disconnects the GUI's stderr. Capture startup diagnostics
        # from the same package when the test display cannot start a window.
        try:
            subprocess.run([str(binary), str(scan)], env=env, timeout=8, check=False)
        except subprocess.TimeoutExpired:
            pass
        raise
    try:
        wid = pointer("search", "--sync", "--onlyvisible", "--pid", pid).splitlines()[-1]
        pointer("windowmove", wid, 0, 0, "windowsize", wid, 1600, 900, "windowfocus", wid)
        wait_for(lambda: tool("status")["result"], lambda s: bool(s["clouds"]) and not s["imports"])
        tool("add_panorama", layer=0, path=str(panorama), position=[0, 0, 0])
        tool("set_camera", yaw=.49, pitch=.5, zoom=.86, pan=[0, 0])
        tool("enter_photo", index=0, layer=0)
        tool("set_panorama", yaw=0, pitch=0, field_of_view=1.1)
        tool("photo_blend", value=.4)
        tool("split_pane", side="right")
        panes = wait_for(lambda: tool("list_panes"), lambda s: any(d["photo_ready"] for d in s["documents"]))
        photo_key = next(d["key"] for d in panes["documents"] if d["photo_ready"])
        assert panes["active_document"] == photo_key
        model_camera = next(d["look"]["camera"] for d in panes["documents"] if d["key"] == "model")
        assert tool("wait_until_idle", timeout_seconds=60)["idle"]

        def screenshot(name):
            time.sleep(.4)
            path = output / (name + ".png")
            tool("screenshot", path=str(path), window=True, max_edge=4096)
            with Image.open(path) as image:
                assert image.size == (1600, 900)
                return image.convert("RGB")

        pointer("mousemove", 5, 5)
        before = screenshot("before")
        click(1162, 92)
        wait_for(lambda: tool("status")["result"], lambda s: s["measure_mode"] == "distance")
        click(930, 480)
        wait_for(lambda: tool("status")["result"]["measure"], lambda m: m and len(m["points"]) == 1)
        click(1170, 550)
        measure = wait_for(lambda: tool("status")["result"]["measure"], lambda m: m and m["finished"])
        first, second = map(tuple, measure["points"])
        assert first in originals and second in originals
        assert first != second and math.isclose(measure["length"], math.dist(first, second), abs_tol=1e-9)
        pointer("mousemove", 5, 5)
        visible = screenshot("measured")
        panes = tool("list_panes")
        assert panes["active_document"] == photo_key
        assert model_camera == next(d["look"]["camera"] for d in panes["documents"] if d["key"] == "model")
        tool("clear_measure")
        cleared = screenshot("cleared")
        counts = {name: changed_pixels(visible, cleared, rect) for name, rect in REGIONS.items()}
        recovery = {name: changed_pixels(before, cleared, rect) for name, rect in REGIONS.items()}
        assert min(counts.values()) > 100 and max(recovery.values()) == 0, (counts, recovery)
        assert hashlib.sha256(scan.read_bytes()).hexdigest() == digest
        return {"version": init["serverInfo"]["version"], "source_sha256": digest, "points": [first, second],
                "distance": measure["length"], "changed_pixels": counts, "changed_after_clear": recovery}
    finally:
        gui["end_process"](pid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    gui = runpy.run_path(str(Path(__file__).resolve().parents[2] / "packaging/gui-smoke.py"))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        env = {**os.environ, "XDG_CONFIG_HOME": str(root/"config"), "XDG_CACHE_HOME": str(root/"cache"),
               "HOME": str(root), "LANG": "C.UTF-8"}
        server = gui["Server"](str(args.binary.resolve()), env)
        try:
            result = exercise(server, root, output, gui, args.binary.resolve(), env)
        finally:
            server.close()
    (output/"result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
