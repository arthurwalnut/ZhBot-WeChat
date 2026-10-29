"""Build an installable Windows archive from explicit project files, without user data."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {"src", "launcher", "scripts", "docs"}
FILES = {
    "ZhBot.exe", "README.md", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md",
    "pyproject.toml", "requirements-lock.txt", "config.bot.example.toml",
    "config.example.toml", "external/helper.lock.json",
}


def main():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    prefix = f"ZhBot-v{version}"
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    # --cached includes staged release files. Untracked plans, probes and local
    # settings never enter the distribution, even if they share a source folder.
    tracked = subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "ls-files", "-z"], cwd=ROOT,
    ).decode("utf-8").split("\0")
    paths = [Path(name) for name in tracked if name and
             (name in FILES or Path(name).parts[0] in DIRECTORIES)]
    wheel = output / f"astra_wechat_lab-{version}-py3-none-any.whl"
    sdist = output / f"astra_wechat_lab-{version}.tar.gz"
    for required in [ROOT / "ZhBot.exe", wheel, sdist, ROOT / "docs" / f"DELIVERY_v{version}.md"]:
        if not required.is_file():
            raise FileNotFoundError(required)
    archive = output / f"{prefix}-windows.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for relative in sorted(paths):
            bundle.write(ROOT / relative, f"{prefix}/{relative.as_posix()}")
        bundle.write(wheel, f"{prefix}/packages/{wheel.name}")
    checksums = output / f"{prefix}-SHA256SUMS.txt"
    lines = []
    for path in [archive, wheel, sdist]:
        with path.open("rb") as stream:
            lines.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {path.name}\n")
    checksums.write_text("".join(lines), encoding="ascii")
    print(archive)
    print(checksums)


if __name__ == "__main__":
    main()
