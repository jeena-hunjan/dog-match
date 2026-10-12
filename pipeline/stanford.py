"""Readers for the Stanford Dogs official lists (MATLAB .mat files from lists.tar)."""

from pathlib import Path

from scipy.io import loadmat


def read_file_list(mat_path: Path) -> list[str]:
    """Image paths such as 'n02085620-Chihuahua/n02085620_5927.jpg'."""
    mat = loadmat(mat_path)
    return [str(entry[0][0]) for entry in mat["file_list"]]


def class_labels(lists_dir: Path) -> list[str]:
    """The 120 class folder names, e.g. 'n02085620-Chihuahua', sorted."""
    return sorted({path.split("/")[0] for path in read_file_list(lists_dir / "file_list.mat")})
