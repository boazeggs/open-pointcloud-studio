import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory

binary = Path(sys.argv[1]).resolve(strict=True)
source = Path(__file__).with_name("survey.obj")
with TemporaryDirectory() as temporary:
    target = Path(temporary) / "survey.glb"
    subprocess.run([binary, "--mesh-export", source, target], check=True)
    data = target.read_bytes()
assert struct.unpack_from("<4sII", data) == (b"glTF", 2, len(data))
length, chunk = struct.unpack_from("<I4s", data, 12)
assert chunk == b"JSON"
doc = json.loads(data[20:20 + length])
assert doc["nodes"][0]["translation"] == [207000.,12.,-474000.]
primitive, = doc["meshes"][0]["primitives"]
payload = 28 + length
def read(accessor, fmt):
    a = doc["accessors"][accessor]
    v = doc["bufferViews"][a["bufferView"]]
    return struct.unpack_from(fmt, data, payload + v.get("byteOffset", 0) + a.get("byteOffset", 0))
coords = read(primitive["attributes"]["POSITION"], "<9f")
assert abs(coords[3] - .001) < 1e-9 and coords[8] == -1
assert read(primitive["attributes"]["COLOR_0"], "<9f") == (1,0,0,0,1,0,0,0,1)
assert read(primitive["indices"], "<3I") == (0,1,2)
digest = hashlib.sha256(data).hexdigest()
print(f"Survey GLB: {len(data)} bytes, SHA-256 {digest}")
assert digest == "43d533b6331b706644428c762fde1b10f3b50515fc242d564137ec7bc89d3818"
