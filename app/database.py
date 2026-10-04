from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# The database location is stored in one place (.env), and this file only reads it.
from app.config import DATABASE_URL

# SQLite allows only one thread by default, but FastAPI uses several,
# so we turn that check off. Other databases don't need this.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# Factory that creates a new database session when called
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Every table class in models.py will inherit from this
class Base(DeclarativeBase):
    pass


# Gives each web request its own session and always closes it afterwards
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()





# 3. The session factory

# bind=engine means every session uses that connection.
# autocommit=False means nothing is saved until you call db.commit(). This lets you undo a half-finished operation.
# autoflush=False means changes aren't sent to the database until you say so, which keeps the behavior predictable.

# 4. The Base class

# In models.py, each table will be written as class Content(Base):. That is how SQLAlchemy knows it should turn the class into a table.

# 5. get_db()

# Every web request gets its own session, and finally closes it even if an error happens. Without this, connections would pile up and the app would eventually freeze.