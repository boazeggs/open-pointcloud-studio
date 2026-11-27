"""Exercise a large mounted scan via the managed desktop's normal MCP operations."""
import hashlib
from pathlib import Path
import struct
import time


SIDE = 1000
LEVELS = 12
POINTS = SIDE * SIDE * LEVELS


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_large_scan(path):
    with path.open("wb") as stream:
        stream.write(f"ply\nformat binary_little_endian 1.0\nelement vertex {POINTS}\n"
                     "property float x\nproperty float y\nproperty float z\nend_header\n".encode())
        for z in range(LEVELS):
            for y in range(SIDE):
                stream.write(b"".join(struct.pack("<fff", x, y, z) for x in range(SIDE)))


def wait_loaded(tool, path, count):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        for layer in tool("stand")["result"]["clouds"]:
            if layer["path"] == str(path) and layer["points"] == count:
                return layer
        time.sleep(.5)
    raise RuntimeError(f"The viewer did not open {path.name} with {count} points")


def verify_large_scan(work, tool, save_to, xyz_coordinates):
    source = work / "large.ply"
    write_large_scan(source)
    original_hash = digest(source)
    start = time.monotonic()
    tool("open", path=str(source))
    original = wait_loaded(tool, source, POINTS)
    assert tool("wait_until_idle", timeout_seconds=60)["idle"]
    tool("set_active", index=original["index"])
    tool("thin", percent=1)
    assert tool("wait_until_idle", timeout_seconds=60)["idle"]
    count = POINTS // 100
    version = work / "edited.xyz"
    save_to(version, count)
    expected = xyz_coordinates(version)
    assert len(expected) == count
    assert all(x.is_integer() and y.is_integer() and z.is_integer() and
               0 <= x < SIDE and 0 <= y < SIDE and 0 <= z < LEVELS for x, y, z in expected)
    version_hash = digest(version)
    tool("open", path=str(version))
    reopened = wait_loaded(tool, version, count)
    tool("set_active", index=reopened["index"])
    readback = work / "readback.xyz"
    save_to(readback, count)
    assert xyz_coordinates(readback) == expected
    assert digest(source) == original_hash and digest(version) == version_hash
    return {"source_points": POINTS, "source_bytes": source.stat().st_size,
            "source_sha256": original_hash, "reopened_unique_points": count,
            "source_and_version_unchanged": True, "elapsed_seconds": round(time.monotonic()-start, 2)}
