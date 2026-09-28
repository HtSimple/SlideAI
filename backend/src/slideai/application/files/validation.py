from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from slideai.core.errors import DomainError

_MIME_TYPES = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".md": {"text/markdown", "text/plain"},
    ".txt": {"text/plain"},
}


@dataclass(frozen=True)
class FileLimits:
    max_file_size_bytes: int = 20 * 1024 * 1024
    max_files_per_task: int = 10
    max_extracted_chars_per_file: int = 2_000_000


@dataclass(frozen=True)
class ValidatedUpload:
    original_name: str
    extension: str
    mime_type: str
    size_bytes: int
    sha256: str


def validate_upload(
    *, filename: str | None, content_type: str | None, content: bytes, limits: FileLimits
) -> ValidatedUpload:
    if not filename or len(filename) > 255 or _has_invalid_path_chars(filename):
        raise DomainError("FILE_NAME_INVALID", "The file name is invalid.")

    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in _MIME_TYPES:
        raise DomainError(
            "FILE_TYPE_MISMATCH", "Only PDF, DOCX, Markdown, and TXT files are supported."
        )

    if not content:
        raise DomainError("FILE_EMPTY", "The uploaded file is empty.")
    if len(content) > limits.max_file_size_bytes:
        raise DomainError("FILE_TOO_LARGE", "The file exceeds the configured size limit.")

    mime_type = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if mime_type not in _MIME_TYPES[extension] or not _signature_matches(extension, content):
        raise DomainError(
            "FILE_TYPE_MISMATCH", "The file extension, MIME type, and content do not match."
        )

    if extension in {".md", ".txt"}:
        try:
            content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as error:
            raise DomainError(
                "FILE_ENCODING_INVALID", "Text files must use UTF-8 encoding."
            ) from error

    return ValidatedUpload(
        original_name=filename,
        extension=extension[1:],
        mime_type=mime_type,
        size_bytes=len(content),
        sha256=sha256(content).hexdigest(),
    )


def _has_invalid_path_chars(filename: str) -> bool:
    return (
        filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
        or any(ord(char) < 32 or ord(char) == 127 for char in filename)
    )


def _signature_matches(extension: str, content: bytes) -> bool:
    if extension == ".pdf":
        return content.startswith(b"%PDF-")
    if extension == ".docx":
        try:
            with ZipFile(BytesIO(content)) as archive:
                members = set(archive.namelist())
                return {
                    "[Content_Types].xml",
                    "word/document.xml",
                }.issubset(members)
        except (BadZipFile, OSError):
            return False
    try:
        content.decode("utf-8-sig", errors="strict")
        return True
    except UnicodeDecodeError:
        return False
