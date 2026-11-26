"""Build and reopen the PCL room scan's index on a mounted SMB share."""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import urllib.request

SOURCE = "https://raw.githubusercontent.com/PointCloudLibrary/data/084fa0e260580cc765ded83de4ec3f495f1d6f1e/tutorials/room_scan1.pcd"
SOURCE_HASH = "52c373a67d8beaa318b5e8c024f06e219f14acc1db28fa7333ff5dc73840428b"
# Raw XYZ from the PCD, decompressed separately with liblzf and converted to <f8.
XYZ_HASH = "0067bb3958b56d1416547aeafd2290692ec74de4306b74f6529c3e978660c01e"
COUNT = 112586


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect_leaves(backing):
    xyz = bytearray(24 * COUNT)
    seen = bytearray(COUNT)
    files = {}
    for path in sorted(backing.rglob("r*.bin")):
        if not re.fullmatch(r"r[0-7]*\.bin", path.name):
            continue
        data = path.read_bytes()
        assert len(data) % 40 == 0
        for coordinates, ordinal in struct.iter_unpack("<24s8xQ", data):
            assert ordinal < COUNT and not seen[ordinal], (path, ordinal)
            seen[ordinal] = 1
            xyz[24 * ordinal:24 * (ordinal + 1)] = coordinates
        stat = path.stat()
        files[path.relative_to(backing).as_posix()] = [stat.st_ino, stat.st_mtime_ns, len(data), digest(data)]
    assert len(files) == 8 and all(seen) and digest(xyz) == XYZ_HASH
    return files


def main():
    phase, binary, mount, backing, work = sys.argv[1:]
    mount, backing, work = map(Path, (mount, backing, work))
    work.mkdir(exist_ok=True, parents=True)
    source = work / "room.pcd"
    env = dict(os.environ, OPS_INDEX_DIR=str(mount / "indexes"), XDG_CACHE_HOME=str(work / "cache"))

    def index():
        return subprocess.run([binary, "--index", str(source)], env=env, capture_output=True, text=True, timeout=120)

    if phase == "build":
        with urllib.request.urlopen(SOURCE, timeout=60) as response:
            sample = response.read()
        assert digest(sample) == SOURCE_HASH
        start = sample.index(b"DATA binary_compressed\n") + len(b"DATA binary_compressed\n")
        length = struct.unpack_from("<I", sample, start)[0]
        source.write_bytes(sample[:start + 8 + length // 2])
        failed = index()
        assert failed.returncode and "599800 compressed bytes, found 299900" in failed.stderr, failed
        assert not any((backing / "indexes").glob("*"))
        source.write_bytes(sample)
    elif phase != "reopen":
        raise ValueError(phase)
    result = index()
    assert result.returncode == 0 and "112586 points" in result.stdout, result
    assert digest(source.read_bytes()) == SOURCE_HASH
    leaves = inspect_leaves(backing / "indexes")
    report = work / "smb-leaves.json"
    if phase == "build":
        report.write_text(json.dumps(leaves, indent=2))
    else:
        assert leaves == json.loads(report.read_text())
    print(f"{phase}: 8 leaves, 4,503,440 bytes, {COUNT:,} unique ordinals; XYZ SHA-256 {XYZ_HASH}", flush=True)


if __name__ == "__main__":
    main()
