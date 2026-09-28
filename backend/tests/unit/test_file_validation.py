import pytest

from slideai.application.files.validation import FileLimits, validate_upload
from slideai.core.errors import DomainError


def test_rejects_extension_mime_signature_mismatch() -> None:
    with pytest.raises(DomainError) as raised:
        validate_upload(
            filename="brief.pdf",
            content_type="application/pdf",
            content=b"not a PDF document",
            limits=FileLimits(),
        )

    assert raised.value.code == "FILE_TYPE_MISMATCH"


def test_rejects_over_limit_and_path_traversal_names() -> None:
    with pytest.raises(DomainError) as too_large:
        validate_upload(
            filename="brief.txt",
            content_type="text/plain",
            content=b"x" * 11,
            limits=FileLimits(max_file_size_bytes=10),
        )
    with pytest.raises(DomainError) as traversal:
        validate_upload(
            filename="../../outside.txt",
            content_type="text/plain",
            content=b"safe text",
            limits=FileLimits(),
        )

    assert too_large.value.code == "FILE_TOO_LARGE"
    assert traversal.value.code == "FILE_NAME_INVALID"
