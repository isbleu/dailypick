"""复现 OpenRouter 推理后异常断流或退出的问题"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.config import Config
# 强制走 OpenRouter
Config.LLM_API_BASE = "https://openrouter.ai/api/v1"
Config.LLM_API_KEY = Config.OPENROUTER_API_KEY
Config.LLM_MODEL = "z-ai/glm-5.2"

from backend.decision_engine import DecisionEngine

print("=== 开始复现 OpenRouter 推理异常 ===")
system_prompt = "你是一个股票量化分析师。"
user_prompt = "请详细分析一下中国A股市场和美股市场的核心差异，请进行不少于500字的深度思考，然后再给出不少于500字的最终结论。"

try:
    result = DecisionEngine._call_llm(system_prompt, user_prompt)
    print(f"\n\n[OK] 正常结束。返回长度: {len(result)}")
except Exception as e:
    print(f"\n[FAIL] 发生异常: {e}")
    import traceback
    traceback.print_exc()
