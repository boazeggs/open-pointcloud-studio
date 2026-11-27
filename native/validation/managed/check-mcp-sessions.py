"""Exercise two managed desktop windows through separate reference MCP clients.

Run under an X11 or Wayland display with mcp-client-requirements.txt installed.
Pass the path to the desktop executable and the expected product version.
"""
import asyncio
from contextlib import asynccontextmanager, ExitStack
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client


@asynccontextmanager
async def connect(url, secret, expected_version):
    client = create_mcp_http_client(headers={"Authorization": "Bearer " + secret})
    async with client, streamable_http_client(url, http_client=client) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            started = await session.initialize()
            assert started.server_info.version == expected_version
            assert set(started.capabilities.model_dump(exclude_none=True)) == {"tools"}
            tools = (await session.list_tools()).tools
            names = {tool.name for tool in tools}
            assert len(names) == len(tools)
            assert {"pointcloud_status", "pointcloud_stand", "pointcloud_export", "pointcloud_opslaan"} <= names
            print(f"Protocol {started.protocol_version}, {len(tools)} tools, no resources", flush=True)
            yield session


async def call(client, name, **args):
    response = await client.call_tool("pointcloud_" + name, args)
    assert not response.is_error, name
    return json.loads(response.content[-1].text)


async def counts(client, total, remaining):
    for _ in range(120):
        clouds = (await call(client, "stand"))["result"]["clouds"]
        if len(clouds) == 1 and clouds[0]["points"] == total and clouds[0].get("remaining", total) == remaining:
            print(f"Selected {total}-point window shows {remaining} remaining", flush=True)
            return
        await asyncio.sleep(0.25)
    raise AssertionError(f"Expected {remaining} of {total} points")


async def exercise(url, secret, app_version, windows):
    async with connect(url, secret, app_version) as first:
        await call(first, "select_instance", pid=windows[0].pid)
        async with connect(url, secret, app_version) as second:
            await call(second, "select_instance", pid=windows[1].pid)
            await counts(first, 1000, 1000)
            await counts(second, 200, 200)
            await call(first, "thin", percent=50)
            await counts(first, 1000, 500)
            await counts(second, 200, 200)
            await call(second, "thin", percent=50)
            await counts(second, 200, 100)
            await counts(first, 1000, 500)
            await call(second, "undo_delete")
            await counts(second, 200, 200)
        for name, remaining in (("undo_delete", 1000), ("redo_delete", 500), ("undo_delete", 1000)):
            await call(first, name)
            await counts(first, 1000, remaining)
    print("Both clients kept their selected window. Undo and redo still worked after the other session closed.")


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


async def run(binary, expected_version, root):
    # Reserve separate ports for the bridge and each window until launch.
    with ExitStack() as cleanup:
        ports = []
        for _ in range(3):
            sock = cleanup.enter_context(socket.socket())
            sock.bind(("127.0.0.1", 0))
            ports.append(sock)
        bridge_port = ports[0].getsockname()[1]
        secret = secrets.token_hex(32)
        env = {**os.environ, "XDG_CONFIG_HOME": str(root/"config"), "XDG_CACHE_HOME": str(root/"cache"),
               "HOME": str(root), "OPENAEC_BEHEERD": "1", "OPENAEC_MAP": str(root),
               "OPENAEC_MCP_ADRES": "127.0.0.1", "OPENAEC_MCP_POORT": str(bridge_port), "OPENAEC_MCP_GEHEIM": secret}
        windows, files = [], {}
        def start(args):
            proc = subprocess.Popen([binary, *args], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            cleanup.callback(stop, proc)
            return proc
        for i, number in enumerate((1000, 200), start=1):
            path = root / f"grid-{number}.xyz"
            data = "".join(f"{j%10} {j//10%10} {j//100}\n" for j in range(number)).encode()
            path.write_bytes(data)
            files[path] = hashlib.sha256(data).digest()
            port = ports[i].getsockname()[1]
            ports[i].close()
            windows.append(start(["--api-port", str(port), str(path)]))
        ports[0].close()
        bridge = start(["--mcp-http"])
        for _ in range(200):
            if any(proc.poll() is not None for proc in [*windows, bridge]):
                raise RuntimeError("Desktop window or HTTP bridge exited")
            discovery = root/"config/open-pointcloud-studio-native/instances"
            if all((discovery/f"instance-{proc.pid}.json").exists() for proc in windows):
                try:
                    with socket.create_connection(("127.0.0.1", bridge_port), timeout=1):
                        break
                except OSError:
                    pass
            await asyncio.sleep(.2)
        else:
            raise RuntimeError("Desktop windows and bridge did not start")
        print(f"Reference Python SDK {version('mcp')}, Studio {expected_version}", flush=True)
        await exercise(f"http://127.0.0.1:{bridge_port}/mcp", secret, expected_version, windows)
    for path, digest in files.items():
        assert hashlib.sha256(path.read_bytes()).digest() == digest
    print("Both source SHA-256 digests still match after closing the windows.")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as folder:
        asyncio.run(asyncio.wait_for(run(Path(sys.argv[1]).resolve(), sys.argv[2], Path(folder)), timeout=180))
