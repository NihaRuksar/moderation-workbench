import os
from dotenv import load_dotenv

load_dotenv()  # reads the .env file and loads its values

AI_API_KEY = os.getenv("AI_API_KEY") #Reads that value. There is no default, so it is None if the key is missing.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./moderation_workbench.db")
AI_MODEL = os.getenv("AI_MODEL", "llama-3.3-70b-versatile")