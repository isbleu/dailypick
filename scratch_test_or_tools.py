import requests
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

api_key = os.getenv('LLM_API_KEY')
if not api_key:
    from dotenv import load_dotenv
    load_dotenv('d:/Vibe/dailypick/.env')
    api_key = os.getenv('LLM_API_KEY')

url = 'https://openrouter.ai/api/v1/chat/completions'
headers = {
    'Authorization': f'Bearer {api_key}',
    'Content-Type': 'application/json'
}

data = {
    'model': 'z-ai/glm-5.2',
    'messages': [
        {'role': 'user', 'content': '请搜索并告诉我今天A股上证指数的收盘点位是多少？必须调用搜索工具。'}
    ],
    'tools': [{'type': 'openrouter:web_search'}],
    'stream': True,
    'include_reasoning': True
}

response = requests.post(url, headers=headers, json=data, stream=True)
for line in response.iter_lines():
    if line:
        line_str = line.decode('utf-8')
        if line_str.startswith('data: ') and line_str != 'data: [DONE]':
            try:
                chunk = json.loads(line_str[6:])
                if 'choices' in chunk:
                    delta = chunk['choices'][0].get('delta', {})
                    # print exactly what delta contains to debug
                    print(json.dumps(delta, ensure_ascii=False))
            except Exception as e:
                pass
