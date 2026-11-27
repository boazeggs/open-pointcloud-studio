"""Run a C client from the previous published SDK with each released library."""
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY = 'OpenAEC-Foundation/open-pointcloud-studio'
VERSIONS = ('2026.45.1', '2026.48.0')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get_sdk(root, version):
    name = f"open-pointcloud-studio-sdk_{version}_{os.environ['SDK_PACKAGE']}"
    for asset in (name, name + '.sha256'):
        subprocess.run(['gh', 'release', 'download', 'v' + version, '-R', REPOSITORY,
                        '-p', asset, '-D', root], check=True)
    archive = root / name
    checksum = digest(archive)
    if checksum != (root / (name + '.sha256')).read_text().split()[0]:
        raise ValueError(f'Checksum mismatch for {name}')
    print(f'{name} SHA-256 {checksum}', flush=True)
    shutil.unpack_archive(str(archive), str(root))
    return root / name.split('.tar.gz')[0].removesuffix('.zip')


def run(root):
    machine = platform.machine().lower()
    if machine != os.environ['SDK_MACHINE']:
        raise ValueError(f'Unexpected runner architecture {machine}')
    old, new = [get_sdk(root, version) for version in VERSIONS]
    work = root / 'client'
    work.mkdir()
    exe = work / ('inspect.exe' if os.name == 'nt' else 'inspect')
    source = old / 'examples' / 'inspect.c'
    if os.name == 'nt':
        library = Path('bin/ops_pointcloud.dll')
        command = ['cl', '/nologo', '/std:c11', '/W4', '/WX', '/D_CRT_SECURE_NO_WARNINGS',
                   '/I' + str(old / 'include'), source, old / 'lib/ops_pointcloud.dll.lib']
    else:
        mac = sys.platform == 'darwin'
        library = Path('lib') / ('libops_pointcloud.dylib' if mac else 'libops_pointcloud.so.1')
        command = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I' + str(old / 'include'),
                   source, '-L' + str(old / 'lib'), '-lops_pointcloud',
                   '-Wl,-rpath,' + ('@loader_path' if mac else '$ORIGIN'), '-o', exe]
    subprocess.run(command, check=True, cwd=work)
    executable_hash = digest(exe)
    for version, sdk in zip(VERSIONS, (old, new)):
        shutil.copy2(sdk / library, work / library.name)
        data = work / version
        data.mkdir()
        output = subprocess.check_output([exe, data], cwd=work, text=True)
        print(output, flush=True)
        expected = f'ops_pointcloud {version}, ABI 1.0: 1000 points read, 500 exported, 500 read through an index'
        if expected not in output or digest(exe) != executable_hash:
            raise ValueError(f'Unexpected client or library result for {version}')
    contract = Path(__file__).with_name('check-sdk-error-contract.py')
    subprocess.run([sys.executable, contract, new / library, VERSIONS[-1]], check=True)
    print(f'Unchanged client SHA-256 {executable_hash}', flush=True)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        run(Path(directory))
