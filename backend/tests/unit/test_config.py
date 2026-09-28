import pytest

from slideai.core.config import Settings


def test_embedding_collection_name_tracks_dimensions_and_version() -> None:
    settings = Settings(embedding_dimensions=64, embedding_version="v2", _env_file=None)

    assert settings.embedding_collection_name == "slideai_chunks_d64_v2"


def test_embedding_version_only_accepts_chroma_safe_characters() -> None:
    with pytest.raises(ValueError):
        Settings(embedding_version="v1/../other", _env_file=None)
