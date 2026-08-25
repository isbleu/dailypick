"""
对比 deepseek/deepseek-v4-flash-0731 与 deepseek/deepseek-v4-pro-0813 在湖滨四季选股决策引擎上的输出效果与性能
"""
import os
import sys
import io
import time
import json
import requests
import traceback
from pathlib import Path

# 确保 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True, write_through=True)

# 确保根目录在 sys.path 中
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.config import Config
from backend.data_collector import DataCollector
from backend.decision_engine import DecisionEngine
from backend.main import load_recent_history

def run_model_test(model_name: str, date_str: str, system_prompt: str, user_prompt: str):
    print(f"\n========================================================")
    print(f"🚀 正在评测模型: {model_name} (基准日期: {date_str})")
    print(f"========================================================")
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {Config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 1.0,
        "max_tokens": 131072,
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
        resp = requests.post(url, headers=headers, json=data, stream=True, timeout=300)
        if resp.status_code != 200:
            print(f"[ERROR] HTTP {resp.status_code}: {resp.text}")
            return {
                "model": model_name,
                "status": "error",
                "error": f"HTTP {resp.status_code}: {resp.text}"
            }
            
        for line in resp.iter_lines():
            if not line:
                continue
            line_str = line.decode('utf-8', errors='ignore')
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
                        
                    if 'reasoning' in delta and delta['reasoning']:
                        reasoning_content += delta['reasoning']
                    elif 'reasoning_content' in delta and delta['reasoning_content']:
                        reasoning_content += delta['reasoning_content']
                        
                    if 'content' in delta and delta['content']:
                        full_content += delta['content']
                        
                    if 'tool_calls' in delta and delta['tool_calls']:
                        tool_calls.append(delta['tool_calls'])
                except Exception:
                    pass
                    
        total_time = time.time() - start_time
        ttft = (first_token_time - start_time) if first_token_time else 0
        
        # 尝试提取并解析 JSON
        raw_text = full_content.strip()
        start_idx = raw_text.find('{')
        end_idx = raw_text.rfind('}')
        
        parsed_json = None
        json_error = None
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = raw_text[start_idx:end_idx+1]
            try:
                parsed_json = json.loads(json_str)
            except Exception as je:
                json_error = str(je)
        else:
            json_error = "未找到有效的 JSON 起止括号"
            
        # 结构与质量评估
        schema_passed = False
        stocks_info = []
        mode = ""
        catalysts_count = 0
        
        if parsed_json:
            required_keys = ["decision_mode", "market_summary", "core_catalysts", "selected_stocks", "full_markdown_report"]
            schema_passed = all(k in parsed_json for k in required_keys)
            mode = parsed_json.get("decision_mode", "")
            catalysts_count = len(parsed_json.get("core_catalysts", []))
            
            for s in parsed_json.get("selected_stocks", []):
                stocks_info.append({
                    "code": s.get("code"),
                    "name": s.get("name"),
                    "score": s.get("score"),
                    "direction": s.get("direction", ""),
                    "logic": s.get("logic", "")[:120]
                })
                
        print(f"\n--- 评测结果摘要 ---")
        print(f"首字响应时延 (TTFT): {ttft:.2f}s")
        print(f"总耗时 (Total Time): {total_time:.2f}s")
        print(f"思考链长度 (Reasoning Chars): {len(reasoning_content)}")
        print(f"输出正文长度 (Content Chars): {len(full_content)}")
        print(f"联网工具调用次数 (Tool Calls): {len(tool_calls)}")
        print(f"JSON 解析状态: {'成功' if parsed_json else '失败: ' + str(json_error)}")
        print(f"Schema 完整性: {'合格' if schema_passed else '不合格'}")
        print(f"判定模式: {mode}")
        print(f"核心催化数: {catalysts_count}")
        print(f"精选标的数: {len(stocks_info)}")
        for s in stocks_info:
            print(f"  - [{s.get('code')}] {s.get('name')} | 评分: {s.get('score')} | 方向: {s.get('direction')}")
            
        return {
            "model": model_name,
            "status": "success",
            "ttft": round(ttft, 2),
            "total_time": round(total_time, 2),
            "reasoning_len": len(reasoning_content),
            "content_len": len(full_content),
            "tool_calls_count": len(tool_calls),
            "json_valid": bool(parsed_json),
            "json_error": json_error,
            "schema_passed": schema_passed,
            "decision_mode": mode,
            "catalysts_count": catalysts_count,
            "stocks_count": len(stocks_info),
            "stocks": stocks_info,
            "parsed_json": parsed_json,
            "reasoning_snippet": reasoning_content[:500],
            "raw_content": full_content
        }
    except Exception as e:
        print(f"[EXCEPTION] {e}")
        traceback.print_exc()
        return {
            "model": model_name,
            "status": "exception",
            "error": str(e)
        }

def main():
    date_str = "20260803" # 使用具备典型多催化、美股分化特征的交易日
    
    print(f"正在准备 {date_str} 的基准测试语料...")
    pdf_text = DataCollector.parse_pdf_file(date_str)
    lhb_df = None # 保持纯语料决策
    us_stocks = DataCollector.fetch_us_stock_status(date_str)
    notion_text = DataCollector.fetch_notion_notes(date_str)
    history_text = load_recent_history(date_str)
    
    system_prompt, user_prompt = DecisionEngine.build_prompts(
        date_str=date_str,
        pdf_text=pdf_text,
        lhb_df=lhb_df,
        us_stocks=us_stocks,
        notion_text=notion_text,
        history_text=history_text
    )
    
    models = [
        "deepseek/deepseek-v4-flash-0731",
        "deepseek/deepseek-v4-pro-0813"
    ]
    
    results = {}
    for m in models:
        res = run_model_test(m, date_str, system_prompt, user_prompt)
        results[m] = res
        time.sleep(3)
        
    # 保存评测结果
    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    report_file = os.path.join(Config.OUTPUT_DIR, "model_comparison_deepseek_v4.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n\n========================================================")
    print(f"🎉 对比评测完成！完整评测数据已保存至: {report_file}")
    print(f"========================================================")

if __name__ == "__main__":
    main()
