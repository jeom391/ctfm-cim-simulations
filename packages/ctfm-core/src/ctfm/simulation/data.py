"""Download and verify published MNIST IDX data; no synthetic fallback."""
import gzip
import hashlib
import os
from pathlib import Path
import struct
import urllib.request
import uuid
import numpy as np

FILES = {
 'train-images-idx3-ubyte.gz': ('f68b3c2dcbeaaa9fbdd348bbdeb94873', 2051, 60000),
 'train-labels-idx1-ubyte.gz': ('d53e105ee54ea40749a09fcbcd1e9432', 2049, 60000),
 't10k-images-idx3-ubyte.gz': ('9fb629c4189551a2d022fa330f9573f3', 2051, 10000),
 't10k-labels-idx1-ubyte.gz': ('ec29112dd5afa0611ce80d1b7f02629c', 2049, 10000),
}
BASE_URL = 'https://ossci-datasets.s3.amazonaws.com/mnist/'


def load_mnist(cache_dir, progress=None):
    cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
    arrays = []; sources = []
    for i, (name, (expected_md5, magic, count)) in enumerate(FILES.items()):
        path = cache_dir / name
        if not path.exists():
            tmp = cache_dir / (name+'.'+uuid.uuid4().hex+'.part')
            try:
                with urllib.request.urlopen(BASE_URL+name, timeout=90) as response, tmp.open('wb') as dest:
                    while chunk := response.read(1024*1024): dest.write(chunk)
                if hashlib.md5(tmp.read_bytes()).hexdigest() != expected_md5:
                    raise ValueError('Published MNIST checksum mismatch: '+name)
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
        compressed = path.read_bytes()
        if hashlib.md5(compressed).hexdigest() != expected_md5:
            raise ValueError('Cached MNIST checksum mismatch: '+name)
        raw = gzip.decompress(compressed)
        actual_magic, actual_count = struct.unpack('>II', raw[:8])
        if actual_magic != magic or actual_count != count:
            raise ValueError('MNIST IDX header mismatch: '+name)
        if magic == 2051:
            rows, cols = struct.unpack('>II', raw[8:16])
            if (rows, cols) != (28,28) or len(raw) != 16+count*784:
                raise ValueError('Invalid MNIST image payload')
            a = np.frombuffer(raw, dtype=np.uint8, offset=16).copy().reshape(count,784)
        else:
            if len(raw) != 8+count: raise ValueError('Invalid MNIST label payload')
            a = np.frombuffer(raw, dtype=np.uint8, offset=8).copy()
            if np.any(a > 9): raise ValueError('Invalid MNIST label')
        arrays.append(a)
        sources.append(dict(filename=name, url=BASE_URL+name, md5=expected_md5,
                            sha256=hashlib.sha256(compressed).hexdigest(), size_bytes=len(compressed)))
        if progress: progress('download', i+1, len(FILES))
    return (*arrays, sources)
