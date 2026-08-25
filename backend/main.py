import os
import sqlite3
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 sys.path 中，防止 ModuleNotFoundError
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
import io
if getattr(sys.stdout, 'encoding', '').lower() != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True, write_through=True)
    except Exception:
        pass

# 彻底清空当前进程的系统代理环境变量，防止 AkShare 和 Notion 因代理配置不当而卡顿和超时
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

from backend.config import Config
from backend.data_collector import DataCollector
from backend.decision_engine import DecisionEngine
from backend.stock_tracker import StockTracker

def init_db():
    """
    初始化 SQLite 共享数据库。满足路径一致性铁律。
    """
    print(f"[DB] 初始化本地共享数据库: {Config.DB_PATH} ...")
    conn = sqlite3.connect(Config.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_decisions (
            date TEXT PRIMARY KEY,
            market_summary TEXT,
            top_three_json TEXT,
            excluded_json TEXT,
            watch_json TEXT,
            operation_summary TEXT,
            full_markdown TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    
    # 增量平滑升级数据库结构，新增 decision_json 字段保存完整原始 JSON
    try:
        cursor.execute("ALTER TABLE daily_decisions ADD COLUMN decision_json TEXT")
        conn.commit()
        print("[DB] 成功检测并增量升级数据库结构，已补齐 decision_json 字段。")
    except sqlite3.OperationalError:
        # 如果列已经存在，说明已经升级过，直接忽略即可
        pass
    conn.close()
    
    # 初始化复盘跟踪表
    StockTracker.init_db()

def save_to_db(result: dict):
    """
    将选股结果存入 SQLite。
    """
    date_val = result.get("date")
    market_summary = result.get("market_summary")
    # 结构化字段转换为 JSON 字符串存入
    top_three_json = json.dumps(result.get("top_three_stocks", []), ensure_ascii=False)
    excluded_json = json.dumps(result.get("excluded_stocks", []), ensure_ascii=False)
    watch_json = json.dumps(result.get("watch_list", []), ensure_ascii=False)
    operation_summary = result.get("operation_summary")
    full_markdown = result.get("full_markdown_report")
    # 保存完整 JSON，避免字段丢失
    decision_json = json.dumps(result, ensure_ascii=False)

    conn = sqlite3.connect(Config.DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO daily_decisions 
            (date, market_summary, top_three_json, excluded_json, watch_json, operation_summary, full_markdown, decision_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (date_val, market_summary, top_three_json, excluded_json, watch_json, operation_summary, full_markdown, decision_json))
        conn.commit()
        print(f"[DB] 选股结果成功持久化到数据库中，日期: {date_val}")
    except Exception as e:
        print(f"[DB] 数据写入异常: {e}")
    finally:
        conn.close()

def load_recent_history(date_str: str) -> str:
    """
    从 SQLite 数据库中读取当前运行日期之前的、最新的 3 条历史选股决策记录，拼装为大模型输入。
    """
    # 严格对齐日期比较格式，防止 SQL 字符串比较时因中划线偏移导致信息穿越 (例如 "2026-07-07" < "20260707" 成立)
    if len(date_str) == 8:
        compare_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    else:
        compare_date = date_str

    conn = sqlite3.connect(Config.DB_PATH)
    cursor = conn.cursor()
    history_lines = []
    try:
        cursor.execute("""
            SELECT date, top_three_json 
            FROM daily_decisions 
            WHERE date < ? 
            ORDER BY date DESC 
            LIMIT 3
        """, (compare_date,))
        rows = cursor.fetchall()
        
        if not rows:
            print("[DB] 数据库中未检索到前 3 个交易日的历史决策记录。")
            return "暂无前 3 个交易日的历史决策记录（首次运行或历史库为空）。"
            
        print(f"[DB] 成功加载近 3 个交易日历史决策参考，日期: {[x[0] for x in rows]}")
            
        for row in rows:
            hist_date, top_three_json = row
            if len(hist_date) == 8:
                formatted_date = f"{hist_date[:4]}-{hist_date[4:6]}-{hist_date[6:]}"
            else:
                formatted_date = hist_date
                
            history_lines.append(f"- 决策日期: {formatted_date}")
            try:
                stocks = json.loads(top_three_json) if top_three_json else []
                if stocks:
                    for s in stocks:
                        history_lines.append(
                            f"  * 排名 {s.get('rank')}: {s.get('name')} ({s.get('code')}) | "
                            f"综合评分: {s.get('score')} | "
                            f"所处方向: {s.get('direction', '未知')} | "
                            f"逻辑: {s.get('logic', '')[:80]}..."
                        )
                else:
                    history_lines.append("  * (该日无推荐标的)")
            except Exception as json_err:
                history_lines.append(f"  * [解析错误] 无法解析该日首选标的: {json_err}")
    except sqlite3.OperationalError:
        return "暂无历史决策记录（数据库尚未初始化）。"
    except Exception as e:
        print(f"[DB] 读取历史决策参考异常: {e}")
        return "读取历史决策参考异常。"
    finally:
        conn.close()
        
    base_history = "\n".join(history_lines)
    
    # 注入实战后效跟踪与胜率复盘反馈 (Feedback Loop)
    try:
        feedback_text = StockTracker.get_recent_feedback_text(date_str, days=3)
        if feedback_text:
            return f"{base_history}\n\n{feedback_text}"
    except Exception as track_err:
        print(f"[TRACKER] 生成实战反馈提示词异常: {track_err}")
        
    return base_history

def verify_and_patch_stock_data(result: dict):
    """
    在线抓取首选三标的真实行情数据，强行覆盖大模型可能虚构的流通市值等数据，杜绝幻觉。
    同时，自动替换 Markdown 报告中对应的硬编码数据，保证报告数据的一致性。
    """
    stocks = result.get("top_three_stocks", [])
    if not stocks:
        return
        
    print("[PATCH] 正在启动首选三标真实行情数据在线校对与物理覆盖程序...")
    import requests
    
    full_markdown = result.get("full_markdown_report", "")
    
    for s in stocks:
        code = s.get("code")
        name = s.get("name")
        old_cap = s.get("market_cap", "")
        old_pct = s.get("pct_change_5d", "")
        if not code:
            continue
            
        if code.startswith("6"):
            symbol = f"sh{code}"
        elif code.startswith("0") or code.startswith("3"):
            symbol = f"sz{code}"
        elif code.startswith("4") or code.startswith("8") or code.startswith("9"):
            symbol = f"bj{code}"
        else:
            continue
            
        try:
            url = f"http://qt.gtimg.cn/q={symbol}"
            r = requests.get(url, timeout=5, proxies={"http": None, "https": None})
            if r.status_code == 200 and "~" in r.text:
                parts = r.text.split("~")
                if len(parts) >= 46:
                    raw_float_cap = float(parts[44]) # 流通市值 (亿元)
                    raw_total_cap = float(parts[45]) # 总市值 (亿元)
                    
                    new_cap = f"约 {raw_float_cap:.1f} 亿(流通) / {raw_total_cap:.1f} 亿(总)"
                    s["market_cap"] = new_cap
                    print(f"  - 成功校对 {name} ({code}) 流通市值: {new_cap} (旧模型输出: {old_cap})")
                    
                    # 自动替换 Markdown 报告正文中的虚假流通市值，防止两端不一致
                    if old_cap and old_cap in full_markdown:
                        full_markdown = full_markdown.replace(old_cap, new_cap)
                        
            # 新增：二次校验近5日表现
            sina_url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=6"
            r_sina = requests.get(sina_url, timeout=5, proxies={"http": None, "https": None})
            if r_sina.status_code == 200 and r_sina.text.strip().startswith("["):
                import json
                k_data = json.loads(r_sina.text)
                if len(k_data) >= 2:
                    start_close = float(k_data[0]["close"])
                    end_close = float(k_data[-1]["close"])
                    actual_days = len(k_data) - 1
                    pct_val = (end_close - start_close) / start_close * 100
                    
                    if pct_val > 0:
                        new_pct = f"近{actual_days}日 +{pct_val:.2f}%"
                    else:
                        new_pct = f"近{actual_days}日 {pct_val:.2f}%"
                        
                    s["pct_change_5d"] = new_pct
                    print(f"  - 成功校对 {name} ({code}) 近期涨跌幅: {new_pct} (旧模型输出: {old_pct})")
                    
                    if old_pct and old_pct in full_markdown:
                        full_markdown = full_markdown.replace(old_pct, new_pct)
                        
        except Exception as patch_err:
            print(f"  - [警告] 校对 {name} ({code}) 行情异常: {patch_err}，保留原模型输出。")
            
    if full_markdown:
        result["full_markdown_report"] = full_markdown

def main():
    parser = argparse.ArgumentParser(description="湖滨四季每日自动化选股策略主入口脚本")
    parser.add_argument("--date", type=str, help="查询日期，格式 YYYYMMDD (例如 20260703)。不传默认使用今天。")
    parser.add_argument("--mock", action="store_true", help="启用模拟决策模式，直接利用历史 Markdown 进行结构化流程闭环。")
    parser.add_argument("--no-sync", action="store_true", help="打开此参数则不上传到云端 GitHub Pages，方便本地测试。")
    parser.add_argument("--api", type=str, choices=["glm", "or-glm", "or-kimi", "or-ds-flash", "or-ds-pro", "or-ds"], default="or-ds",
                        help="选择大模型 API 通道: glm=智谱官方, or-glm=OpenRouter GLM, or-kimi=OpenRouter Kimi, or-ds-flash=DeepSeek V4 Flash, or-ds-pro=DeepSeek V4 Pro, or-ds=DeepSeek(默认)。")
    parser.add_argument("--lhb", action="store_true", help="是否拉取并使用龙虎榜数据，默认不拉取。")
    args = parser.parse_args()

    # 1. 确定日期
    if args.date:
        date_str = args.date
    else:
        date_str = datetime.now().strftime("%Y%m%d")

    # 1.5 根据 --api 参数动态切换 API 通道
    if args.api == "or-glm":
        Config.LLM_API_BASE = "https://openrouter.ai/api/v1"
        Config.LLM_API_KEY = Config.OPENROUTER_API_KEY
        Config.LLM_MODEL = "z-ai/glm-5.2"
        print(f"[API] 已切换至 OpenRouter 通道 (模型: {Config.LLM_MODEL})")
    elif args.api == "or-kimi":
        Config.LLM_API_BASE = "https://openrouter.ai/api/v1"
        Config.LLM_API_KEY = Config.OPENROUTER_API_KEY
        Config.LLM_MODEL = "moonshotai/kimi-k3"
        print(f"[API] 已切换至 OpenRouter 通道 (模型: {Config.LLM_MODEL})")
    elif args.api == "or-ds-flash":
        Config.LLM_API_BASE = "https://openrouter.ai/api/v1"
        Config.LLM_API_KEY = Config.OPENROUTER_API_KEY
        Config.LLM_MODEL = "deepseek/deepseek-v4-flash-0731"
        print(f"[API] 已切换至 OpenRouter 通道 (模型: {Config.LLM_MODEL})")
    elif args.api == "or-ds-pro":
        Config.LLM_API_BASE = "https://openrouter.ai/api/v1"
        Config.LLM_API_KEY = Config.OPENROUTER_API_KEY
        Config.LLM_MODEL = "deepseek/deepseek-v4-pro-0813"
        print(f"[API] 已切换至 OpenRouter 通道 (模型: {Config.LLM_MODEL})")
    elif args.api == "or-ds":
        Config.LLM_API_BASE = "https://openrouter.ai/api/v1"
        Config.LLM_API_KEY = Config.OPENROUTER_API_KEY
        Config.LLM_MODEL = "deepseek/deepseek-v4-pro-0813"
        print(f"[API] 已切换至 OpenRouter 通道 (模型: {Config.LLM_MODEL})")
    else:
        print(f"[API] 使用智谱官方通道 (模型: {Config.LLM_MODEL})")

    print(f"\n==================== 🚀 湖滨四季自动化选股系统启动 ({date_str}) ====================")
    
    # 打印配置校验
    warnings = Config.validate()
    for w in warnings:
        print(f"[警告] {w}")

    # 2. 初始化数据库
    init_db()

    # 3. 盘前数据拉取与解析
    # 3.1 龙虎榜数据
    if args.lhb:
        prev_trade_day = DataCollector.get_previous_trading_day(date_str)
        print(f"[LHB] 当前运行日期: {date_str}，决策参考的前一交易日龙虎榜日期: {prev_trade_day}")
        lhb_df = DataCollector.fetch_lhb_data(prev_trade_day)
    else:
        lhb_df = None
        print(f"[LHB] 龙虎榜数据拉取已通过参数关闭。")
    
    # 3.2 隔夜美股行情
    us_stocks = DataCollector.fetch_us_stock_status(date_str)
    
    # 3.3 星球 PDF 逻辑简报
    pdf_text = DataCollector.parse_pdf_file(date_str)
    
    # 3.4 Notion 备忘笔记
    notion_text = DataCollector.fetch_notion_notes(date_str)

    # 校验基础输入是否存在
    if not pdf_text and (lhb_df is None or lhb_df.empty):
        print("[错误] 今日缺失星球逻辑且无龙虎榜上榜个股，基础信息严重不足，系统无法判定选股逻辑，终止运行。")
        return

    # 4. 调用决策打分引擎
    decision_result = None
    # 格式化日期：20260703 -> 2026-07-03 和 2026年7月3日
    formatted_date_cn = f"{date_str[:4]}年{int(date_str[4:6])}月{int(date_str[6:])}日"
    date_val = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    md_filename = f"湖滨四季.今日选股结果（{formatted_date_cn}）.md"
    examples_md_path = os.path.join(Config.PROJECT_ROOT, "examples", md_filename)

    # 如果启用了 mock 或者未配置 API Key 且存在备份 Markdown
    is_fallback = False
    if args.mock or (not Config.LLM_API_KEY and os.path.exists(examples_md_path)):
        print(f"[MOCK] 检测到模拟运行请求或大模型 API Key 未配置，自动启动历史 Markdown 数据导入机制，文件: {md_filename}")
        try:
            from backend.import_history import parse_markdown_report
            decision_result = parse_markdown_report(examples_md_path, date_val)
            is_fallback = True
            print(f"[MOCK] 成功基于本地历史 Markdown 报告，自动构建结构化数据。")
        except Exception as mock_err:
            print(f"[MOCK] 模拟解析历史文件失败: {mock_err}")

    if not decision_result:
        # 获取近 3 个交易日历史选股决策参考
        history_text = load_recent_history(date_str)
        try:
            decision_result = DecisionEngine.generate_stock_decision(
                date_str=date_str,
                pdf_text=pdf_text,
                lhb_df=lhb_df,
                us_stocks=us_stocks,
                notion_text=notion_text,
                history_text=history_text
            )
        except Exception as e:
            print(f"[错误] 大模型决策打分失败: {e}")
            if os.path.exists(examples_md_path):
                print(f"[降级提示] 检测到大模型 API 异常，但本地有该日期的选股报告备份，正在自动启动本地 Markdown 兜底解析...")
                try:
                    from backend.import_history import parse_markdown_report
                    decision_result = parse_markdown_report(examples_md_path, date_val)
                    is_fallback = True
                    print(f"[降级成功] 成功通过解析本地历史报告完成当前日期的流程闭环。")
                except Exception as mock_err:
                    print(f"[降级失败] 解析历史报告失败: {mock_err}")
                    return
            else:
                return

    # 4.5 启动物理覆盖与校对，清洗并修正大模型生成的个股流通市值
    if decision_result:
        verify_and_patch_stock_data(decision_result)

    # 5. 保存结果与输出报告
    # 5.1 保存结构化 JSON 文件
    json_path = os.path.join(Config.OUTPUT_DIR, f"result_{date_str}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(decision_result, f, ensure_ascii=False, indent=2)
    print(f"[OUTPUT] 结构化选股 JSON 结果已保存: {json_path}")

    # 5.2 保存 Markdown 报告文件
    # 格式化日期：20260703 -> 2026年7月3日
    formatted_date_cn = f"{date_str[:4]}年{int(date_str[4:6])}月{int(date_str[6:])}日"
    md_filename = f"湖滨四季.今日选股结果（{formatted_date_cn}）.md"
    md_path = os.path.join(Config.OUTPUT_DIR, md_filename)
    
    markdown_content = decision_result.get("full_markdown_report", "")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    print(f"[OUTPUT] 策略选股 Markdown 报告已导出: {md_path}")

    # 5.3 如果是原生大模型生成的报告，则复制一份到工作区的 examples/ 目录下以满足样本归档
    if not is_fallback:
        examples_dir = os.path.join(Config.PROJECT_ROOT, "examples")
        os.makedirs(examples_dir, exist_ok=True)
        examples_md_path = os.path.join(examples_dir, md_filename)
        with open(examples_md_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        print(f"[OUTPUT] 已归档今日选股报告至 examples 文件夹: {examples_md_path}")
    else:
        print(f"[OUTPUT] 本次为降级/MOCK运行，跳过 examples 样本归档覆盖。")

    # 5.4 存入共享数据库并更新复盘跟踪
    if not args.no_sync:
        save_to_db(decision_result)
        try:
            print("[TRACKER] 正在自动增量更新选股历史复盘与走势跟踪...")
            StockTracker.sync_all_decisions()
        except Exception as trk_err:
            print(f"[TRACKER] 自动复盘更新异常: {trk_err}")
    else:
        print("[DB] --no-sync 模式下跳过持久化至共享数据库，避免污染线上环境。")
    
    # 5.5 自动同步数据至 GitHub Pages 仓库 (isbleu.github.io/pick)
    if not args.no_sync:
        try:
            from backend.sync_to_github import sync as sync_to_github
            sync_to_github()
        except Exception as sync_err:
            print(f"[SYNC] 自动同步至 GitHub Pages 失败: {sync_err}")
    else:
        print("[SYNC] --no-sync 参数已开启，本次测试结果将不上传至云端看板。")
    
    print("\n==================== 🎉 选股系统当日任务运行完毕 ====================")

if __name__ == "__main__":
    main()
