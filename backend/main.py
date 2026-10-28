import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("BASETEN_API_KEY")
if not api_key:
    raise ValueError("Lipseste BASETEN_API_KEY din fisierul .env!")

client = OpenAI(
    base_url="https://inference.baseten.co/v1",
    api_key=api_key,
)

print("Trimit cererea către Baseten...")

response = client.chat.completions.create(
    model="meta-models/muse-spark-open-1026",
    messages=[
        {"role": "system", "content": "Raspunde scurt si concis în limba romana."},
        {"role": "user", "content": "Salut! Confirma te rog ca esti activ si pregatit pentru hackathon."}
    ],
)

print("\n--- Raspuns de la model ---")
print(response.choices[0].message.content)