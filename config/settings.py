from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Groq API key — for summarization (Llama 3.3 70B)
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

# Google Gemini API key — for writing the newsletter (Gemini 2.0 Flash)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Tavily API key — for web search
TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')

# Email sender address
EMAIL_FROM = os.getenv('EMAIL_FROM')

# Email recipient address
EMAIL_TO = os.getenv('EMAIL_TO')

# Gmail app password or SMTP password
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
