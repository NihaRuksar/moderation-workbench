import os
from dotenv import load_dotenv

load_dotenv()  # reads the .env file and loads its values

AI_API_KEY = os.getenv("AI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./moderation.db")
AI_MODEL = os.getenv("AI_MODEL", "llama-3.3-70b-versatile")