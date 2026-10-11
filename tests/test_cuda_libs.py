import io
import zipfile

import pytest

from spette import cuda_libs


class FakeResponse:
    def __init__(self, data=b"", json=None):
        self._data, self._json = data, json

    def json(self):
        return self._json

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeRequests:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def get(self, url, **kwargs):
        self.asked.append(url)
        return self.pages[url]


def entry(package, host="https://files.pythonhosted.org/x.whl", sha=None):
    version, pinned, _size = cuda_libs.PINNED[package]
    return {"filename": f"{package}-{version}-py3-none-win_amd64.whl", "url": host,
            "digests": {"sha256": sha or pinned}, "size": 1}


def test_every_package_has_a_pinned_version_hash_and_size():
    for package, (version, sha, size) in cuda_libs.PINNED.items():
        assert version[0].isdigit() and len(sha) == 64 and size > 0


def test_the_pinned_version_is_asked_for_and_its_hash_must_match():
    package = "nvidia-cublas-cu12"
    version = cuda_libs.PINNED[package][0]
    page = f"https://pypi.org/pypi/{package}/{version}/json"
    wheel = cuda_libs._find_wheel(FakeRequests({page: FakeResponse(json={"urls": [entry(package)]})}), package)
    assert wheel["digests"]["sha256"] == cuda_libs.PINNED[package][1] and wheel["size"] == cuda_libs.PINNED[package][2]
    for bad in (entry(package, sha="0" * 64), entry(package, host="https://evil.example/x.whl")):
        with pytest.raises(cuda_libs.CudaDownloadError):
            cuda_libs._find_wheel(FakeRequests({page: FakeResponse(json={"urls": [bad]})}), package)


def test_a_download_larger_than_expected_or_with_a_wrong_hash_is_refused(tmp_path):
    wheel = {"url": "https://files.pythonhosted.org/x", "size": 10, "digests": {"sha256": "0" * 64}}
    requests = FakeRequests({wheel["url"]: FakeResponse(b"x" * 20)})
    with pytest.raises(cuda_libs.CudaDownloadError, match="larger"):
        cuda_libs._download_file(requests, wheel, tmp_path / "a", lambda m: None, None)
    wheel["size"] = 20
    with pytest.raises(cuda_libs.CudaDownloadError, match="checksum"):
        cuda_libs._download_file(requests, wheel, tmp_path / "b", lambda m: None, None)


def test_only_flat_dll_names_from_bin_folders_are_extracted(tmp_path):
    archive = tmp_path / "w.whl"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nvidia/cublas/bin/cublas64_12.dll", b"dll")
        zf.writestr("nvidia/cublas/bin/../../../evil.dll", b"x")
        zf.writestr("nvidia/cublas/include/header.h", b"h")
    target = tmp_path / "out"
    target.mkdir()
    assert cuda_libs._extract_dlls(archive, target) == ["cublas64_12.dll"]
    assert sorted(p.name for p in target.iterdir()) == ["cublas64_12.dll"]
    assert not (tmp_path / "evil.dll").exists()
