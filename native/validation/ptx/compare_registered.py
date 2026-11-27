"""Compare every registered point and its RGB in the Studio and PDAL binary PLYs."""
import json
import math
from pathlib import Path
import struct
import sys


def points(path, studio):
    record = struct.Struct("<dddBBBH" if studio else "<dddBBB")
    with path.open("rb") as stream:
        assert stream.readline().strip() == b"ply"
        assert stream.readline().strip() == b"format binary_little_endian 1.0"
        names = []
        count = None
        for line in stream:
            parts = line.split()
            if parts[:2] == [b"element", b"vertex"]:
                count = int(parts[2])
            elif parts[0] == b"property":
                names.append(tuple(parts[1:]))
            elif parts == [b"end_header"]:
                break
        assert count == 6488111, count
        expected = [(b"double", k) for k in (b"x", b"y", b"z")]
        expected += [(b"uchar", k) for k in (b"red", b"green", b"blue")]
        if studio:
            expected.append((b"ushort", b"intensity"))
        assert names == expected, names
        remaining = count
        while remaining:
            size = min(65536, remaining)
            block = stream.read(size * record.size)
            assert len(block) == size * record.size
            yield from record.iter_unpack(block)
            remaining -= size
        assert stream.read(1) == b""


def compare(studio, reference):
    maximum = 0.0
    count = 0
    equal = 0
    for a, b in zip(points(studio, True), points(reference, False), strict=True):
        delta = [abs(x-y) for x, y in zip(a[:3], b[:3])]
        assert all(math.isfinite(value) for value in delta)
        assert a[3:6] == b[3:6], (count, a, b)
        maximum = max(maximum, *delta)
        equal += a[:3] == b[:3]
        count += 1
    assert count == 6488111 and maximum < 1e-6, (count, maximum)
    return {"count": count, "xyz_exact": equal, "maximum_coordinate_difference": maximum,
            "rgb_matches": count}


if __name__ == "__main__":
    print(json.dumps(compare(Path(sys.argv[1]), Path(sys.argv[2]))))
