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
        {"role": "user", "content": "今天惠科股份上龙虎榜了吗？必须联网搜索今天的最新数据。"}
    ],
    "temperature": 0.2,
    "stream": True
}

if "glm" in Config.LLM_MODEL.lower() and "openrouter.ai" in Config.LLM_API_BASE.lower():
    data["tools"] = [{"type": "openrouter:web_search"}]

url = f"{Config.LLM_API_BASE.rstrip('/')}/chat/completions"
print(f"Requesting {url}")

try:
    response = requests.post(url, json=data, headers=headers, stream=True)
    response.raise_for_status()
    for line in response.iter_lines():
        if line:
            print("RAW:", line.decode('utf-8'))
except Exception as e:
    print("ERROR:", e)
