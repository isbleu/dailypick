"""
精准对比 DecisionEngine 在使用两个模型时的真实输出
"""
import os
import sys
import io
import json
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True, write_through=True)

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.config import Config
from backend.data_collector import DataCollector
from backend.decision_engine import DecisionEngine
from backend.main import load_recent_history

date_str = "20260803"
pdf_text = DataCollector.parse_pdf_file(date_str)
lhb_df = None
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
    ("deepseek/deepseek-v4-flash-0731", "Flash 0731"),
    ("deepseek/deepseek-v4-pro-0813", "Pro 0813")
]

for model_id, model_label in models:
    print(f"\n{'='*60}")
    print(f"Testing DecisionEngine with {model_label} ({model_id})")
    print(f"{'='*60}")
    
    Config.LLM_API_BASE = "https://openrouter.ai/api/v1"
    Config.LLM_API_KEY = Config.OPENROUTER_API_KEY
    Config.LLM_MODEL = model_id
    
    t0 = time.time()
    try:
        res = DecisionEngine.generate_stock_decision(
            date_str=date_str,
            pdf_text=pdf_text,
            lhb_df=lhb_df,
            us_stocks=us_stocks,
            notion_text=notion_text,
            history_text=history_text
        )
        elapsed = time.time() - t0
        print(f"\n[OK] 决策生成成功! 耗时: {elapsed:.2f}s")
        print(f"Top 3 标的:")
        for s in res.get("top_three_stocks", []):
            print(f"  - Rank {s.get('rank')}: [{s.get('code')}] {s.get('name')} | 得分: {s.get('score')} | 方向: {s.get('direction')}")
        print(f"排除数量: {len(res.get('excluded_stocks', []))}")
        print(f"观察池数量: {len(res.get('watch_list', []))}")
        print(f"Full Markdown Length: {len(res.get('full_markdown_report', ''))}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"\n[FAIL] 决策生成失败! 耗时: {elapsed:.2f}s, 错误: {e}")
