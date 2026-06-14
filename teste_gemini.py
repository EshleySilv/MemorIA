import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

modelo = genai.GenerativeModel("gemini-flash-latest")

resposta = modelo.generate_content("Olá")

print(resposta.text)