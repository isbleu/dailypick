"""直接测试重构后的 _call_llm 函数，验证智谱官方通道仍然正常工作"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.decision_engine import DecisionEngine

print("=== 测试智谱官方通道 (当前 .env 默认配置) ===")

system_prompt = "你是一个有用的助手。"
user_prompt = "请搜索一下2026年7月7日的美股纳斯达克指数收盘点位。"

try:
    result = DecisionEngine._call_llm(system_prompt, user_prompt)
    print(f"\n\n[OK] 返回长度: {len(result)}")
    print(f"[OK] 内容预览: {result[:150]}...")
except Exception as e:
    print(f"\n[FAIL] {e}")
