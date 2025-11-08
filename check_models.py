import google.generativeai as genai
import os
from dotenv import load_dotenv

# Carga la API key desde tu archivo .env
load_dotenv()
try:
    genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
except Exception as e:
    print(f"❌ ERROR: No se pudo configurar Gemini. ¿Falta la API Key en .env? - {e}")
    exit()

print("Buscando modelos disponibles para tu API key...")

try:
    # Itera sobre todos los modelos que tu clave puede "ver"
    for m in genai.list_models():
        # Imprime el nombre del modelo
        print(f"- {m.name}")
except Exception as e:
    print(f"\n--- ¡ERROR! ---")
    print(f"La llamada a 'list_models' falló. Esto confirma que hay un problema de API o de librería.")
    print(f"Error: {e}")

print("\nBúsqueda terminada.")