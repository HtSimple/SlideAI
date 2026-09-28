import os
import tempfile
from pathlib import Path
from uuid import UUID


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, task_id: UUID, stored_name: str, content: bytes) -> None:
        destination = self._path(task_id, stored_name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=destination.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, destination)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise

    def read(self, task_id: UUID, stored_name: str) -> bytes:
        return self._path(task_id, stored_name).read_bytes()

    def delete(self, task_id: UUID, stored_name: str) -> None:
        path = self._path(task_id, stored_name)
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass

    def _path(self, task_id: UUID, stored_name: str) -> Path:
        if Path(stored_name).name != stored_name or "/" in stored_name or "\\" in stored_name:
            raise ValueError("stored file names must be isolated names")
        task_root = (self.root / str(task_id)).resolve()
        path = (task_root / stored_name).resolve()
        if not path.is_relative_to(task_root):
            raise ValueError("file path escapes the configured storage root")
        return path
