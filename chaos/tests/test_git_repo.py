from pathlib import Path

import git
import pytest
from chaos.git_repo import BoutiqueDeployRepo


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    remote_path = tmp_path / "remote.git"
    git.Repo.init(remote_path, bare=True)
    # Seed the bare remote with one commit so clone has something to check out.
    seed_path = tmp_path / "seed"
    seed_repo = git.Repo.init(seed_path)
    (seed_path / "overlay.yaml").write_text("placeholder: true\n")
    seed_repo.index.add(["overlay.yaml"])
    seed_repo.index.commit("seed")
    seed_repo.create_remote("origin", str(remote_path))
    default_branch = seed_repo.active_branch.name
    seed_repo.remote("origin").push(default_branch)
    return remote_path


def test_ensure_cloned_clones_fresh_path(bare_remote: Path, tmp_path: Path) -> None:
    local_path = tmp_path / "working-copy"
    repo = BoutiqueDeployRepo(remote_url=str(bare_remote), local_path=local_path)

    repo.ensure_cloned()

    assert (local_path / "overlay.yaml").exists()
    assert (local_path / ".git").is_dir()


def test_ensure_cloned_pulls_when_already_cloned(bare_remote: Path, tmp_path: Path) -> None:
    local_path = tmp_path / "working-copy"
    repo = BoutiqueDeployRepo(remote_url=str(bare_remote), local_path=local_path)
    repo.ensure_cloned()

    # Someone else pushes a new commit to the remote.
    other_clone_path = tmp_path / "other-clone"
    other_repo = git.Repo.clone_from(str(bare_remote), other_clone_path)
    (other_clone_path / "overlay.yaml").write_text("placeholder: false\n")
    other_repo.index.add(["overlay.yaml"])
    other_repo.index.commit("update")
    other_repo.remote("origin").push()

    repo2 = BoutiqueDeployRepo(remote_url=str(bare_remote), local_path=local_path)
    repo2.ensure_cloned()

    assert (local_path / "overlay.yaml").read_text() == "placeholder: false\n"


def test_write_commit_push_and_head_sha(bare_remote: Path, tmp_path: Path) -> None:
    local_path = tmp_path / "working-copy"
    repo = BoutiqueDeployRepo(remote_url=str(bare_remote), local_path=local_path)
    repo.ensure_cloned()

    repo.write_file("overlay.yaml", "placeholder: changed\n")
    sha = repo.commit_and_push("test: change placeholder")

    assert sha == repo.head_sha()
    assert len(sha) == 40

    # A fresh clone from the remote sees the pushed change.
    verify_path = tmp_path / "verify-clone"
    git.Repo.clone_from(str(bare_remote), verify_path)
    assert (verify_path / "overlay.yaml").read_text() == "placeholder: changed\n"
