"""Compare the entitlements in each signed architecture of the published apps."""
from pathlib import Path
import json
import plistlib
import subprocess
import tempfile

def run(*args):
    return subprocess.run(args, capture_output=True, check=True)

def entitlements(target, arch):
    result = run("codesign", "--display", "--architecture", arch, "--entitlements", "-", "--xml", target)
    if result.stdout.strip():
        decoded = plistlib.loads(result.stdout)
        assert isinstance(decoded, dict), decoded
        return decoded
    warnings = [line for line in result.stderr.decode().splitlines() if not line.startswith("Executable=")]
    assert not warnings, warnings
    return {}

versions = ["2026.45.1", "2026.48.0"]
archs = ["arm64", "x86_64"]
programs = ["open-pointcloud-studio", "OpenCADStudio"]
report = {}
with tempfile.TemporaryDirectory() as temporary:
    tmp = Path(temporary)
    control = tmp / "reader-control"
    code = tmp / "control.c"
    code.write_text("int main(void) { return 0; }")
    run("clang", "-arch", "arm64", "-arch", "x86_64", code, "-o", control)
    rights = {"com.apple.security.app-sandbox": True}
    plist = tmp / "control.plist"
    plist.write_bytes(plistlib.dumps(rights))
    run("codesign", "--force", "--sign", "-", "--entitlements", plist, control)
    for arch in archs:
        assert entitlements(control, arch) == rights
    for version in versions:
        mount = tmp / version
        mount.mkdir()
        dmg = Path("downloads") / f"open-pointcloud-studio_{version}_macos-universal.dmg"
        run("hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", mount, dmg)
        try:
            app = mount / "Open Pointcloud Studio.app"
            run("codesign", "--verify", "--deep", "--strict", "--all-architectures", app)
            bin_dir = app / "Contents" / "MacOS"
            assert {p.name for p in bin_dir.iterdir()} == set(programs)
            info = report[version] = {}
            for name in programs:
                executable = bin_dir / name
                assert set(run("lipo", "-archs", executable).stdout.decode().split()) == set(archs)
                slices = info[name] = {}
                for arch in archs:
                    details = run("codesign", "--display", "--verbose=4", "--architecture", arch, executable).stderr.decode().splitlines()
                    assert any(s.startswith("Authority=Developer ID Application:") for s in details)
                    assert "TeamIdentifier=7KFV4QY98M" in details
                    assert any("flags=" in s and "runtime" in s for s in details)
                    digest, = [s.split("=", 1)[1] for s in details if s.startswith("CDHash=")]
                    slices[arch] = {"cdhash": digest, "entitlements": entitlements(executable, arch), "team": "7KFV4QY98M", "hardenedRuntime": True}
                assert slices[archs[0]]["cdhash"] != slices[archs[1]]["cdhash"]
        finally:
            run("hdiutil", "detach", mount)
print(json.dumps(report, indent=2), flush=True)
Path("entitlements.json").write_text(json.dumps(report, indent=2))
for name in programs:
    for arch in archs:
        assert report[versions[0]][name][arch]["entitlements"] == report[versions[1]][name][arch]["entitlements"], (name, arch)
