"""Exercise the public ABI of an extracted Studio SDK from a separate process."""
import ctypes as c
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading


class Point(c.Structure):
    _fields_ = [
        ("x", c.c_double), ("y", c.c_double), ("z", c.c_double),
        ("intensity", c.c_uint16), ("r", c.c_uint8), ("g", c.c_uint8),
        ("b", c.c_uint8), ("classification", c.c_uint8),
        ("flags", c.c_uint8), ("reserved", c.c_uint8), ("ordinal", c.c_uint64),
    ]


class ExportOptions(c.Structure):
    _fields_ = [
        ("struct_size", c.c_uint32), ("format", c.c_int32),
        ("box", c.c_void_p), ("max_points", c.c_uint64),
    ]


PointsCallback = c.CFUNCTYPE(c.c_int32, c.POINTER(Point), c.c_size_t, c.c_void_p)
OK, IO, CANCELLED, LIMIT = 0, 2, 5, 7


def check(condition, description):
    if not condition:
        raise RuntimeError(description)


def exercise(library, version, root):
    sdk = c.CDLL(str(library))
    signatures = {
        "ops_version": (c.c_char_p, []),
        "ops_abi_version": (c.c_uint32, []),
        "ops_last_error": (c.c_char_p, []),
        "ops_cloud_open": (c.c_int32, [c.c_char_p, c.POINTER(c.c_void_p)]),
        "ops_cloud_free": (None, [c.c_void_p]),
        "ops_cloud_read": (c.c_int32, [c.c_void_p, c.c_void_p, c.c_size_t, PointsCallback, c.c_void_p]),
        "ops_cloud_export": (c.c_int32, [c.c_void_p, c.c_char_p, c.POINTER(ExportOptions), c.POINTER(c.c_uint64)]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(sdk, name)
        function.restype = result
        function.argtypes = arguments

    check(sdk.ops_version().decode() == version and sdk.ops_abi_version() == 0x10000,
          "Unexpected product or ABI version")
    cloud_path = root / "source.xyz"
    cloud_path.write_text("0 1 2\n1 2 3\n2 3 4\n3 4 5\n4 5 6\n", encoding="ascii")
    source = str(cloud_path).encode("utf-8")

    def open_on_worker():
        check(sdk.ops_last_error() is None, "Worker inherited an error")
        cloud = c.c_void_p()
        check(sdk.ops_cloud_open(source, c.byref(cloud)) == OK, "Worker open failed")
        sdk.ops_cloud_free(cloud)

    cloud = c.c_void_p()
    check(sdk.ops_cloud_open(source, c.byref(cloud)) == OK, "Cannot open fixture")
    try:
        # Start with a real, live handle value in an independent output slot.
        missing = c.c_void_p(cloud.value)
        status = sdk.ops_cloud_open(str(root / "missing.xyz").encode("utf-8"), c.byref(missing))
        message = sdk.ops_last_error()
        check(status == IO and missing.value is None and message, "Missing-file status or output mismatch")
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(open_on_worker).result()
        check(sdk.ops_last_error() == message, "Worker success changed the calling thread's error")

        caller = threading.get_ident()
        batches = []
        stop = True

        @PointsCallback
        def receive(points, count, _):
            # Copy values while the SDK owns the callback buffer.
            batches.append((threading.get_ident(), [(points[i].ordinal, points[i].x) for i in range(count)]))
            return int(stop)

        status = sdk.ops_cloud_read(cloud, None, 2, receive, None)
        check(status == CANCELLED and sdk.ops_last_error(), "Callback did not cancel with an error")
        check(batches == [(caller, [(0, 0.0), (1, 1.0)])], "Cancelled read delivered unexpected points")
        stop = False
        batches.clear()
        check(sdk.ops_cloud_read(cloud, None, 2, receive, None) == OK, "Retry failed")
        expected = [(caller, [(0, 0.0), (1, 1.0)]), (caller, [(2, 2.0), (3, 3.0)]), (caller, [(4, 4.0)])]
        check(batches == expected and sdk.ops_last_error() is None, "Retry lost points or retained an error")

        destination = root / "limited.xyz"
        options = ExportOptions(c.sizeof(ExportOptions), 0, None, 2)
        written = c.c_uint64(5)
        status = sdk.ops_cloud_export(cloud, str(destination).encode("utf-8"), c.byref(options), c.byref(written))
        check(status == LIMIT and written.value == 0 and not destination.exists() and sdk.ops_last_error(),
              "Limited export status, count or file mismatch")
    finally:
        sdk.ops_cloud_free(cloud)
    print(f"{version} ABI 1.0 passed missing-file output reset, thread-local error, callback cancellation, "
          "three retry batches and export-limit rollback", flush=True)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        exercise(Path(sys.argv[1]).resolve(), sys.argv[2], Path(directory))
