import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
# 我们支持当前目录或项目根目录下的 .env
project_root = Path(__file__).resolve().parent.parent
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

class Config:
    # --- 基础路径配置 (满足路径一致性铁律) ---
    PROJECT_ROOT = str(project_root)
    # 所有进程使用绝对路径，避免在不同目录下创建同名碎文件
    PDF_DIR = os.getenv("PDF_DIR", str(project_root / "daily_morning_summary"))
    OUTPUT_DIR = os.getenv("OUTPUT_DIR", str(project_root / "output"))
    DB_PATH = os.getenv("DB_PATH", str(project_root / "warehouse.db"))
    LOG_DIR = os.getenv("LOG_DIR", str(project_root / "log"))
    
    # --- Notion API 配置 ---
    NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
    NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "")
    TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
    
    # --- 大模型 API 配置 ---
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o") # 亦可配置为 deepseek-chat, gemini 等
    
    # --- 数据采集过滤参数 ---
    # 个股流通市值上限（单位：元），默认200亿（200 * 100,000,000）
    MAX_MARKET_CAP = float(os.getenv("MAX_MARKET_CAP", 200 * 100000000))
    # 个股流通市值下限（单位：元），默认10亿
    MIN_MARKET_CAP = float(os.getenv("MIN_MARKET_CAP", 10 * 100000000))
    # 龙虎榜最低买入金额（单位：元），默认1000万
    MIN_LHB_NET_BUY = float(os.getenv("MIN_LHB_NET_BUY", 10000000))

    @classmethod
    def validate(cls):
        """校验关键配置项，如果缺失则返回警告"""
        warnings = []
        if not cls.LLM_API_KEY:
            warnings.append("LLM_API_KEY 未配置，大模型判定将无法运行。")
        if not cls.NOTION_TOKEN or not cls.NOTION_DATABASE_ID:
            warnings.append("Notion 配置不完整，系统将默认采用本地 Markdown 目录进行输入。")
        return warnings

# 自动创建必要文件夹
os.makedirs(Config.PDF_DIR, exist_ok=True)
os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
os.makedirs(Config.LOG_DIR, exist_ok=True)
