"""One-time download of JS libraries with pinned SHA-512 checksums."""
import base64
import hashlib
import io
import json
import os
import tarfile
import urllib.request

REGISTRY = "https://registry.npmjs.org/"
MAX_BYTES = 60 * 1024 * 1024

PINNED_CHECKSUMS = {
    "react@18.3.1": "wS+hAgJShR0KhEvPJArfuPVN1+Hz1t0Y6n5jLrGQbkb4urgPE/0Rve+1kMB1v/oWgHgm4WIcV+i7F2pTVj+2iQ==",
    "react-dom@18.3.1": "5m4nQKp+rZRb09LNH59GM4BxTh9251/ylbKIbpe7TpGxfJ+9kv6BLkLBXIjjspbgbnIBNqlI23tRnTWT0snUIw==",
    "@babel/standalone@7.26.4": "SF+g7S2mhTT1b7CHyfNjDkPU1corxg4LPYsyP0x5KuCl+EbtBQHRLqr9N3q7e7+x7NQ5LYxQf8mJ2PmzebLr0A==",
    "prop-types@15.8.1": "oj87CgZICdulUohogVAR7AjlC0327U4el4L6eAvOqCeudMDVU0NThNaV+b9Df4dXgSP1gXMTnPdhfe/2qDH5cg==",
    "recharts@2.15.0": "cIvMxDfpAmqAmVgc4yb7pgm/O1tmmkl/CjrvXuW+62/+7jj/iF9Ykm+hb/UJt42TREHMyd3gb+pkgoa2MxgDIw==",
    "lucide-react@0.383.0": "13xlG0CQCJtzjSQYwwJ3WRqMHtRj3EXmLlorrARt7y+IHnxUCp3XyFNL1DfaGySWxHObDvnu1u1dV+0VMKHUSg==",
    "lodash@4.17.21": "v2kDEe57lecTulaDIuNTPy3Ry4gLGJ6Z1O3vE1krgXZNrsQ+LFTGHVxVjcXPs17LhbZVGedAJv8XZ1tvj5FvSg==",
    "d3@7.9.0": "e1U46jVP+w7Iut8Jt8ri1YsPOvFpg46k+K8TpCb0P+zjCkjkPnV7WzfDJzMHy1LnA+wj5pLT1wjO901gLXeEhA==",
    "mathjs@13.2.0": "P5PZoiUX2Tkghkv3tsSqlK0B9My/ErKapv1j6wdxd0MOrYQ30cnGE4LH/kzYB2gA5rN46Njqc4cFgJjaxgijoQ==",
    "papaparse@5.4.1": "HipMsgJkZu8br23pW15uvo6sib6wne/4woLZPlFf3rpDyMe9ywEXUsuD7+6K9PRkJlVT51j/sCOYDKGGS3ZJrw==",
}

PACKAGES = [
    ("react", "18.3.1", [("package/umd/react.production.min.js", "react.production.min.js")]),
    ("react-dom", "18.3.1", [("package/umd/react-dom.production.min.js", "react-dom.production.min.js")]),
    ("@babel/standalone", "7.26.4", [("package/babel.min.js", "babel.min.js")]),
    ("prop-types", "15.8.1", [("package/prop-types.min.js", "prop-types.min.js")]),
    ("recharts", "2.15.0", [("package/umd/Recharts.js", "Recharts.js")]),
    ("lucide-react", "0.383.0", [("package/dist/umd/lucide-react.min.js", "lucide-react.min.js")]),
    ("lodash", "4.17.21", [("package/lodash.min.js", "lodash.min.js")]),
    ("d3", "7.9.0", [("package/dist/d3.min.js", "d3.min.js")]),
    ("mathjs", "13.2.0", [("package/lib/browser/math.js", "math.js")]),
    ("papaparse", "5.4.1", [("package/papaparse.min.js", "papaparse.min.js")]),
]
ALL_FILES = [out for _n, _v, files in PACKAGES for _i, out in files]

def missing_files(vendor_dir, files):
    return [f for f in files if not os.path.isfile(os.path.join(vendor_dir, f))]

def _get(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": "artifact-deck"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise RuntimeError("Download too large: " + url)
    return data

def _verify(data, name, version):
    key = "%s@%s" % (name, version)
    expected = PINNED_CHECKSUMS.get(key)
    if expected is None:
        raise RuntimeError("No pinned checksum for %s" % key)
    got = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if got != expected:
        raise RuntimeError("Checksum mismatch for %s: download discarded" % key)

def download_all(vendor_dir, progress=None):
    os.makedirs(vendor_dir, exist_ok=True)
    total = len(PACKAGES)
    for i, (name, version, files) in enumerate(PACKAGES):
        if not missing_files(vendor_dir, [out for _i, out in files]):
            continue
        if progress: progress(i, total, name)
        meta = json.loads(_get("%s%s/%s" % (REGISTRY, name, version)))
        dist = meta["dist"]
        tarball = _get(dist["tarball"])
        _verify(tarball, name, version)
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tf:
            for inner, out in files:
                member = tf.extractfile(inner)
                if member is None:
                    raise RuntimeError("%s is missing %s" % (name, inner))
                tmp = os.path.join(vendor_dir, out + ".part")
                with open(tmp, "wb") as f:
                    f.write(member.read())
                os.replace(tmp, os.path.join(vendor_dir, out))
    if progress: progress(total, total, "")
