import os
import sys
import time
import json
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend.config import Config

models = [
    "deepseek/deepseek-v4-flash-0731",
    "deepseek/deepseek-v4-pro-0813"
]

url = "https://openrouter.ai/api/v1/chat/completions"
headers = {
    "Authorization": f"Bearer {Config.OPENROUTER_API_KEY}",
    "Content-Type": "application/json"
}

prompt = "请简要分析当前AI芯片和算力光模块领域的近期催化逻辑，并列出2个代表性A股标的及理由。请以JSON格式输出，包含 summary 和 stocks 字段。"

results = {}

for m in models:
    print(f"\n==========================================")
    print(f"Testing model: {m}")
    print(f"==========================================")
    
    data = {
        "model": m,
        "messages": [
            {"role": "system", "content": "你是一位专业的A股买方投资研究专家，擅长逻辑发掘与定量筛选。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 4096,
        "stream": True,
        "reasoning": {
            "effort": "medium",
            "exclude": False
        },
        "tools": [
            {"type": "openrouter:web_search"}
        ]
    }
    
    start_time = time.time()
    first_token_time = None
    full_content = ""
    reasoning_content = ""
    tool_calls = []
    
    try:
        resp = requests.post(url, headers=headers, json=data, stream=True, timeout=60)
        print(f"HTTP Status: {resp.status_code}")
        
        if resp.status_code != 200:
            print(f"Error: {resp.text}")
            results[m] = {"error": resp.text}
            continue
            
        for line in resp.iter_lines():
            if not line:
                continue
            line_str = line.decode('utf-8')
            if line_str.startswith('data: '):
                raw = line_str[6:].strip()
                if raw == '[DONE]':
                    break
                try:
                    chunk = json.loads(raw)
                    if not chunk.get('choices'):
                        continue
                    delta = chunk['choices'][0].get('delta', {})
                    
                    if first_token_time is None:
                        first_token_time = time.time()
                        
                    # 抓取推理过程
                    if 'reasoning' in delta and delta['reasoning']:
                        reasoning_content += delta['reasoning']
                    elif 'reasoning_content' in delta and delta['reasoning_content']:
                        reasoning_content += delta['reasoning_content']
                        
                    # 抓取正文
                    if 'content' in delta and delta['content']:
                        full_content += delta['content']
                        
                    # 抓取 tool_calls
                    if 'tool_calls' in delta and delta['tool_calls']:
                        tool_calls.append(delta['tool_calls'])
                except Exception as e:
                    pass
                    
        total_time = time.time() - start_time
        ttft = (first_token_time - start_time) if first_token_time else 0
        
        print(f"TTFT (首字耗时): {ttft:.2f}s")
        print(f"Total Time (总耗时): {total_time:.2f}s")
        print(f"Reasoning Length: {len(reasoning_content)} chars")
        print(f"Content Length: {len(full_content)} chars")
        print(f"Tool Calls Count: {len(tool_calls)}")
        print(f"\n--- Content Sample (First 300 chars) ---")
        print(full_content[:300])
        
        results[m] = {
            "ttft": round(ttft, 2),
            "total_time": round(total_time, 2),
            "reasoning_len": len(reasoning_content),
            "content_len": len(full_content),
            "tool_calls_count": len(tool_calls),
            "content": full_content,
            "reasoning_sample": reasoning_content[:200]
        }
    except Exception as err:
        print(f"Exception during request: {err}")
        results[m] = {"error": str(err)}

with open("scratch/model_compare_preliminary.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n\nSaved preliminary results to scratch/model_compare_preliminary.json")
