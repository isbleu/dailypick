import os
import sys
import io
from datetime import datetime
import argparse

# 确保项目根目录在 sys.path 中
from pathlib import Path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 禁用系统代理
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

from backend.config import Config
from backend.data_collector import DataCollector

def dump_real_prompt(date_str):
    print(f"[DUMP] 正在为日期 {date_str} 收集真实选股输入数据...")
    
    # 1. 采集数据
    lhb_df = DataCollector.fetch_lhb_data(date_str)
    us_stocks = DataCollector.fetch_us_stock_status(date_str)
    pdf_text = DataCollector.parse_pdf_file(date_str)
    notion_text = DataCollector.fetch_notion_notes(date_str)
    
    from backend.main import load_recent_history
    history_text = load_recent_history(date_str)
    
    # 2. 调用最新决策引擎组装 Prompt
    from backend.decision_engine import DecisionEngine
    system_prompt, user_prompt = DecisionEngine.build_prompts(
        date_str, pdf_text, lhb_df, us_stocks, notion_text, history_text
    )
    
    # 3. 合并输出到 markdown 中
    output_md_path = os.path.join(Config.PROJECT_ROOT, "output", f"prompt_{date_str}.md")
    
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write(f"# 湖滨四季自动化选股系统运行 Prompt 集合 ({date_str})\n\n")
        f.write("> **说明**：此文件为该运行日期下系统实际向大模型发起的 System Prompt 和 User Prompt 的合并内容，您可以将其复制并在平台进行手动接口调用或调试。\n\n")
        
        f.write("## 1. ⚙️ SYSTEM PROMPT (系统角色/打分金律/格式蒸馏)\n\n")
        f.write("```text\n")
        f.write(system_prompt)
        f.write("\n```\n\n")
        
        f.write("## 2. 📝 USER PROMPT (数据输入/输出规范)\n\n")
        f.write("```text\n")
        f.write(user_prompt)
        f.write("\n```\n")
        
    print(f"[DUMP] 真实 Prompt 已成功导出到文件: {output_md_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导出真实 Prompt 用于调试")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y%m%d"), help="指定日期，格式如 20260707")
    args = parser.parse_args()
    
    dump_real_prompt(args.date)
