import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("❌ API key not found!")
else:
    # The new SDK uses a Client object
    client = genai.Client(api_key=api_key)

    try:
        # New syntax: models.generate
        response = client.models.generate_content(
            model="gemini-2.5-flash", contents="Say hello in one sentence."
        )
        print("✅ API key loaded!")
        print("🤖 Gemini says:", response.text)
    except Exception as e:
        print(f"❌ Error: {e}")
