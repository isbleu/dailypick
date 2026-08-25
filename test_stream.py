import os
import json
import requests
from backend.config import Config

headers = {
    "Authorization": f"Bearer {Config.LLM_API_KEY}",
    "Content-Type": "application/json"
}

data = {
    "model": Config.LLM_MODEL,
    "messages": [
        {"role": "user", "content": "你好，请回复'测试成功'"}
    ],
    "temperature": 0.2,
    "stream": True
}

if "glm" in Config.LLM_MODEL.lower() and "openrouter.ai" in Config.LLM_API_BASE.lower():
    data["tools"] = [{"type": "openrouter:web_search"}]

url = f"{Config.LLM_API_BASE.rstrip('/')}/chat/completions"
print(f"Requesting {url} with model {Config.LLM_MODEL}")

try:
    response = requests.post(url, json=data, headers=headers, stream=True)
    response.raise_for_status()
    for line in response.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            print("RAW LINE:", line_str)
except Exception as e:
    print("ERROR:", e)
    if 'response' in locals() and response is not None:
        print("RESPONSE BODY:", response.text)
