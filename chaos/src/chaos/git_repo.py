from pathlib import Path

import git


class BoutiqueDeployRepo:
    def __init__(self, remote_url: str, local_path: Path) -> None:
        self.remote_url = remote_url
        self.local_path = local_path
        self._repo: git.Repo | None = None

    def ensure_cloned(self) -> None:
        if (self.local_path / ".git").is_dir():
            self._repo = git.Repo(self.local_path)
            self._repo.remote("origin").pull()
            return
        self._repo = git.Repo.clone_from(self.remote_url, self.local_path)

    @property
    def repo(self) -> git.Repo:
        if self._repo is None:
            raise RuntimeError("call ensure_cloned() before using the repo")
        return self._repo

    def write_file(self, relative_path: str, content: str) -> None:
        target = self.local_path / relative_path
        target.write_text(content)

    def commit_and_push(self, message: str) -> str:
        self.repo.git.add(A=True)
        self.repo.index.commit(message)
        self.repo.remote("origin").push()
        return self.repo.head.commit.hexsha

    def head_sha(self) -> str:
        return self.repo.head.commit.hexsha
