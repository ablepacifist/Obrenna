import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from codebase_agent.pathsafety import PathSafetyError, resolve_safe_path, validate_new_root


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")
    return tmp_path


def test_normal_relative_path_resolves(root: Path):
    resolved = resolve_safe_path(root, "src/main.py")
    assert resolved == (root / "src" / "main.py").resolve()


def test_dotdot_traversal_rejected(root: Path):
    with pytest.raises(PathSafetyError):
        resolve_safe_path(root, "../../etc/passwd")


def test_absolute_posix_path_rejected(root: Path):
    with pytest.raises(PathSafetyError):
        resolve_safe_path(root, "/etc/passwd")


def test_absolute_windows_drive_path_rejected(root: Path):
    with pytest.raises(PathSafetyError):
        resolve_safe_path(root, "C:\\Windows\\System32\\config")


def test_null_byte_rejected(root: Path):
    with pytest.raises(PathSafetyError):
        resolve_safe_path(root, "src/\x00main.py")


def test_empty_path_rejected(root: Path):
    with pytest.raises(PathSafetyError):
        resolve_safe_path(root, "")


def test_dotdot_that_stays_inside_root_is_allowed(root: Path):
    # src/../src/main.py never actually leaves root, even though it contains '..'
    resolved = resolve_safe_path(root, "src/../src/main.py")
    assert resolved == (root / "src" / "main.py").resolve()


def test_symlink_escape_rejected(root: Path, tmp_path_factory: pytest.TempPathFactory):
    outside = tmp_path_factory.mktemp("outside")
    secret = outside / "secret.txt"
    secret.write_text("classified")

    link = root / "escape"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")

    with pytest.raises(PathSafetyError):
        resolve_safe_path(root, "escape/secret.txt")


def test_junction_escape_rejected(root: Path, tmp_path_factory: pytest.TempPathFactory):
    # NTFS junctions are directory reparse points, same escape vector as
    # symlinks for path resolution, but don't require admin/Developer Mode --
    # gives real coverage of this class of bug on locked-down Windows setups.
    if os.name != "nt":
        pytest.skip("junction points are a Windows-only mechanism")

    import subprocess

    outside = tmp_path_factory.mktemp("outside_junction")
    secret = outside / "secret.txt"
    secret.write_text("classified")

    link = root / "escape_junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"junction creation failed in this environment: {result.stderr}")

    with pytest.raises(PathSafetyError):
        resolve_safe_path(root, "escape_junction/secret.txt")


def test_write_under_git_dir_rejected(root: Path):
    git_dir = root / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("")
    with pytest.raises(PathSafetyError):
        resolve_safe_path(root, ".git/config", for_write=True)


def test_read_under_git_dir_allowed(root: Path):
    git_dir = root / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("x")
    # Reads are not blocked by the VCS-dir guard, only writes.
    resolved = resolve_safe_path(root, ".git/config", for_write=False)
    assert resolved == (git_dir / "config").resolve()


def test_case_insensitive_root_match_on_same_filesystem(root: Path):
    # Passing the root itself back (identity case) must always succeed.
    resolved = resolve_safe_path(root, ".")
    assert resolved == root.resolve()


def test_validate_new_root_rejects_filesystem_root():
    fs_root = Path(root_anchor())
    with pytest.raises(PathSafetyError):
        validate_new_root(fs_root)


def test_validate_new_root_rejects_home_directory():
    with pytest.raises(PathSafetyError):
        validate_new_root(Path.home())


def test_validate_new_root_accepts_normal_project_dir(root: Path):
    validated = validate_new_root(root)
    assert validated == root.resolve()


def root_anchor() -> str:
    return Path.cwd().resolve().anchor
