"""测试 OpenRouter 通道的流式输出"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config import Config
Config.LLM_API_BASE = "https://openrouter.ai/api/v1"
Config.LLM_API_KEY = Config.OPENROUTER_API_KEY
Config.LLM_MODEL = "z-ai/glm-5.2"

from backend.decision_engine import DecisionEngine

print("=== 测试 OpenRouter 通道 (z-ai/glm-5.2 + web_search + reasoning) ===")

system_prompt = "你是一个有用的助手。"
user_prompt = "请搜索一下2026年7月7日的美股纳斯达克指数收盘点位。"

try:
    result = DecisionEngine._call_llm(system_prompt, user_prompt)
    print(f"\n\n[OK] 返回长度: {len(result)}")
    print(f"[OK] 内容预览: {result[:150]}...")
except Exception as e:
    print(f"\n[FAIL] {e}")
