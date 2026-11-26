from pathlib import Path
import numpy as np
import sys
p=Path(sys.argv[1])
block=np.empty((1_000_000,3),dtype='<f4')
block[:,0]=np.tile(np.arange(1000),1000)
block[:,1]=np.repeat(np.arange(1000),1000)
header=b'ply\nformat binary_little_endian 1.0\nelement vertex 500000000\nproperty float x\nproperty float y\nproperty float z\nend_header\n'
with p.open('xb') as f:
    f.write(header)
    for z in range(500):
        block[:,2]=z
        block.tofile(f)
assert p.stat().st_size==6_000_000_000+len(header)
with p.open('rb') as f:
    f.seek(-12,2)
    assert np.fromfile(f,dtype='<f4').tolist()==[999,999,499]
