from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Metadata base for application tables and Alembic migrations."""
