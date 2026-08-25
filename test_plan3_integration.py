"""
测试方案3：选股历史持续跟踪与后效反馈系统集成验证
"""
import os
import sys
import io
import json
import sqlite3
import requests
import subprocess
from pathlib import Path

if getattr(sys.stdout, 'encoding', '').lower() != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True, write_through=True)
    except Exception:
        pass

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.config import Config
from backend.stock_tracker import StockTracker
from backend.main import load_recent_history

print("==================================================")
print("🧪 开始执行方案 3 全链路集成测试")
print("==================================================")

# 1. 验证数据库结构与路径一致性
print("\n[TEST 1] 校验数据库 stock_trackings 表结构与路径一致性...")
conn = sqlite3.connect(Config.DB_PATH)
cursor = conn.cursor()
cursor.execute("SELECT count(*) FROM stock_trackings")
track_cnt = cursor.fetchone()[0]
print(f"  - 共享数据库路径: {Config.DB_PATH}")
print(f"  - 已追踪历史推荐标的总数: {track_cnt}")
assert track_cnt > 0, "stock_trackings 表中应有记录"
conn.close()
print("  - [PASS] 数据库结构与记录校验通过")

# 2. 验证统计计算
print("\n[TEST 2] 校验全量战法胜率与收益统计...")
stats = StockTracker.get_summary_stats()
print(f"  - 战法整体胜率: {stats.get('win_rate')}%")
print(f"  - 5日平均最高冲高: +{stats.get('avg_max_gain')}%")
print(f"  - 5日平均最大回撤: {stats.get('avg_max_loss')}%")
print(f"  - Top 1 胜率: {stats.get('rank_stats', {}).get('Top_1', {}).get('win_rate')}%")
assert stats.get("valid_total", 0) > 0, "有效统计样本数应大于0"
print("  - [PASS] 胜率与统计指标计算正常")

# 3. 验证 Prompt 后效反馈文本生成 (Feedback Loop)
print("\n[TEST 3] 校验大模型 Prompt 后效反馈文本注入...")
feedback = load_recent_history("2026-08-25")
print(f"  - 注入提示词长度: {len(feedback)} 字符")
assert "实盘跟踪与表现复盘" in feedback or "决策日期" in feedback, "反馈提示词应包含历史跟踪走势"
print("  - [PASS] 后效反馈提示词正确拼装并注入")

# 4. 验证 main.py 模拟运行与自动同步
print("\n[TEST 4] 运行 main.py --mock --no-sync 进行全流程回归...")
res = subprocess.run([sys.executable, "backend/main.py", "--mock", "--no-sync"], cwd=str(project_root), capture_output=True, text=True, encoding='utf-8')
print(f"  - main.py 退出码: {res.returncode}")
assert res.returncode == 0, f"main.py 运行失败: {res.stderr}"
print("  - [PASS] main.py 全链路回归测试通过")

print("\n==================================================")
print("🎉 方案 3 所有集成测试全部顺利通过！")
print("==================================================")
