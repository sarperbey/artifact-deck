"""One-time download of the JS libraries React artifacts need, so they can
run fully offline afterwards. Every tarball is checked against the checksum
published by the npm registry before anything is written to disk."""
import base64
import hashlib
import io
import json
import os
import tarfile
import urllib.request

REGISTRY = "https://registry.npmjs.org/"
MAX_BYTES = 60 * 1024 * 1024

# (npm package, pinned version, [(path inside the tarball, local file name)])
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


def _verify(data, dist):
    integrity = dist.get("integrity", "")
    if integrity.startswith("sha512-"):
        got = base64.b64encode(hashlib.sha512(data).digest()).decode()
        ok = got == integrity[len("sha512-"):]
    elif dist.get("shasum"):
        ok = hashlib.sha1(data).hexdigest() == dist["shasum"]
    else:
        raise RuntimeError("No checksum published for package")
    if not ok:
        raise RuntimeError("Checksum mismatch, download discarded")


def download_all(vendor_dir, progress=None):
    """Fetch every package that still has a missing file. Raises on any error."""
    os.makedirs(vendor_dir, exist_ok=True)
    total = len(PACKAGES)
    for i, (name, version, files) in enumerate(PACKAGES):
        if not missing_files(vendor_dir, [out for _i, out in files]):
            continue
        if progress:
            progress(i, total, name)
        meta = json.loads(_get("%s%s/%s" % (REGISTRY, name, version)))
        dist = meta["dist"]
        tarball = _get(dist["tarball"])
        _verify(tarball, dist)
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tf:
            for inner, out in files:
                member = tf.extractfile(inner)
                if member is None:
                    raise RuntimeError("%s is missing %s" % (name, inner))
                tmp = os.path.join(vendor_dir, out + ".part")
                with open(tmp, "wb") as f:
                    f.write(member.read())
                os.replace(tmp, os.path.join(vendor_dir, out))
    if progress:
        progress(total, total, "")
