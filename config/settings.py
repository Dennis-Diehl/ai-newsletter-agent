from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Google Gemini API key — for scoring, summarization, and newsletter writing
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Tavily API key — for web search
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')

# Email sender address
EMAIL_FROM = os.getenv('EMAIL_FROM')

# Email recipient address
EMAIL_TO = os.getenv('EMAIL_TO')

# Gmail app password or SMTP password
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
