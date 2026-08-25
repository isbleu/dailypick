"""
湖滨四季选股历史持续跟踪与自动复盘引擎 (Stock Tracker & Performance Feedback)
- 自动提取历史每日 Top 3 推荐标的
- 跟踪 T+1 至 T+5 真实交易行情与盈亏表现
- 计算全量胜率、盈亏比与催化方向表现
- 为决策引擎提供自适应学习与后效反馈 (Feedback Loop)
"""
import os
import sys
import io
import json
import sqlite3
import requests
import traceback
from datetime import datetime
from pathlib import Path

# 确保 UTF-8 编码输出
if getattr(sys.stdout, 'encoding', '').lower() != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True, write_through=True)
    except Exception:
        pass

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.config import Config

class StockTracker:
    
    @staticmethod
    def get_symbol(code: str) -> str:
        """格式化股票代码，生成对应的行情接口代码"""
        c = str(code).strip().zfill(6)
        if c.startswith(('60', '68', '90')):
            return f"sh{c}"
        elif c.startswith(('00', '20', '30')):
            return f"sz{c}"
        elif c.startswith(('4', '8', '92')):
            return f"bj{c}"
        return f"sz{c}"

    @classmethod
    def init_db(cls):
        """初始化 stock_trackings 数据表，严格遵循路径一致性铁律"""
        conn = sqlite3.connect(Config.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_trackings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_date TEXT NOT NULL,       -- 决策日期 YYYY-MM-DD
                code TEXT NOT NULL,                -- 股票代码 6位
                name TEXT NOT NULL,                -- 股票名称
                rank INTEGER NOT NULL,             -- 当日排名 1, 2, 3
                score REAL,                        -- 决策评分
                direction TEXT,                    -- 所属主线/方向
                buy_date TEXT,                     -- 买入日 (通常为决策日 T)
                buy_price REAL,                    -- 买入开盘价
                t0_close REAL,                     -- T日收盘价
                t0_return REAL,                    -- T日日内收益率 (%)
                t1_date TEXT,                      -- T+1 交易日
                t1_close REAL,                     -- T+1 收盘价
                t1_return REAL,                    -- T+1 收益率 (%)
                t3_date TEXT,                      -- T+3 交易日
                t3_close REAL,                     -- T+3 收盘价
                t3_return REAL,                    -- T+3 收益率 (%)
                t5_date TEXT,                      -- T+5 交易日
                t5_close REAL,                     -- T+5 收盘价
                t5_return REAL,                    -- T+5 收益率 (%)
                max_gain_5d REAL,                  -- 5日内最高冲高涨幅 (%)
                max_loss_5d REAL,                  -- 5日内最大回撤跌幅 (%)
                win_loss_status TEXT,              -- WIN / LOSS / DRAW / PENDING
                notes TEXT,                        -- 复盘备注
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(decision_date, code)
            )
        """)
        conn.commit()
        conn.close()

    @classmethod
    def fetch_kline_data(cls, code: str, datalen: int = 60) -> list:
        """从新浪财经快速拉取日 K 线数据"""
        symbol = cls.get_symbol(code)
        url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
        try:
            r = requests.get(url, timeout=6, proxies={"http": None, "https": None})
            if r.status_code == 200 and r.text.strip().startswith("["):
                data = json.loads(r.text)
                return data
        except Exception as e:
            print(f"[TRACKER] 拉取 {code} K线异常: {e}")
        return []

    @classmethod
    def sync_all_decisions(cls) -> dict:
        """
        全量同步并复盘 daily_decisions 中的历史选股
        """
        cls.init_db()
        conn = sqlite3.connect(Config.DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT date, top_three_json, decision_json FROM daily_decisions ORDER BY date ASC")
        rows = cursor.fetchall()
        
        print(f"[TRACKER] 正在扫描历史选股决策，共检索到 {len(rows)} 个历史交易日...")
        
        processed_count = 0
        updated_count = 0
        
        for row in rows:
            decision_date = row[0] # YYYY-MM-DD
            # 格式统一化
            if len(decision_date) == 8 and decision_date.isdigit():
                decision_date = f"{decision_date[:4]}-{decision_date[4:6]}-{decision_date[6:]}"
                
            top_json = row[1]
            if not top_json:
                continue
                
            try:
                stocks = json.loads(top_json)
            except Exception:
                continue
                
            if not isinstance(stocks, list):
                continue
                
            for s in stocks:
                code = str(s.get("code", "")).strip().zfill(6)
                name = str(s.get("name", "")).strip()
                rank = int(s.get("rank", 0)) if s.get("rank") else 1
                score = float(s.get("score", 0)) if s.get("score") else None
                direction = str(s.get("direction", ""))
                
                if not code or len(code) != 6 or not name:
                    continue
                    
                processed_count += 1
                
                # 拉取该股票的 K 线
                klines = cls.fetch_kline_data(code, datalen=60)
                if not klines:
                    continue
                    
                # 寻找决策日及之后的 K 线 (按 day 升序)
                # 决策日格式比较: 'YYYY-MM-DD'
                decision_idx = None
                for idx, k in enumerate(klines):
                    k_day = k.get("day", "")
                    if k_day >= decision_date:
                        decision_idx = idx
                        break
                        
                if decision_idx is None:
                    continue
                    
                sub_klines = klines[decision_idx:]
                if not sub_klines:
                    continue
                    
                # 买入日与开盘价 (T日)
                t0_k = sub_klines[0]
                buy_date = t0_k.get("day", decision_date)
                buy_price = float(t0_k.get("open", 0))
                
                if buy_price <= 0:
                    continue
                    
                t0_close = float(t0_k.get("close", 0))
                t0_return = round((t0_close - buy_price) / buy_price * 100, 2)
                
                # 计算 T+1, T+3, T+5 表现
                t1_date = None
                t1_close = None
                t1_return = None
                if len(sub_klines) >= 2:
                    t1_k = sub_klines[1]
                    t1_date = t1_k.get("day")
                    t1_close = float(t1_k.get("close", 0))
                    t1_return = round((t1_close - buy_price) / buy_price * 100, 2)
                    
                t3_date = None
                t3_close = None
                t3_return = None
                if len(sub_klines) >= 4:
                    t3_k = sub_klines[3]
                    t3_date = t3_k.get("day")
                    t3_close = float(t3_k.get("close", 0))
                    t3_return = round((t3_close - buy_price) / buy_price * 100, 2)
                    
                t5_date = None
                t5_close = None
                t5_return = None
                if len(sub_klines) >= 6:
                    t5_k = sub_klines[5]
                    t5_date = t5_k.get("day")
                    t5_close = float(t5_k.get("close", 0))
                    t5_return = round((t5_close - buy_price) / buy_price * 100, 2)
                    
                # 5日内最高冲高与最大回撤 (取最多前 5 根 K 线)
                window_klines = sub_klines[:5]
                highs = [float(k.get("high", buy_price)) for k in window_klines]
                lows = [float(k.get("low", buy_price)) for k in window_klines]
                
                max_high = max(highs)
                min_low = min(lows)
                
                max_gain_5d = round((max_high - buy_price) / buy_price * 100, 2)
                max_loss_5d = round((min_low - buy_price) / buy_price * 100, 2)
                
                # 胜负判定规则
                # 1. 5日内冲高 >= +3.0% 或 T+3收盘 >= +2.0% -> WIN
                # 2. 5日内最大冲高 < 0% 且 T+3收盘 <= -2.5% -> LOSS
                # 3. 数据不足 3 天 -> PENDING
                if len(sub_klines) < 3:
                    win_loss_status = "PENDING"
                elif max_gain_5d >= 3.0 or (t3_return is not None and t3_return >= 2.0):
                    win_loss_status = "WIN"
                elif max_gain_5d < 1.0 and (t3_return is not None and t3_return <= -2.5):
                    win_loss_status = "LOSS"
                else:
                    win_loss_status = "DRAW"
                    
                # 写入数据库
                cursor.execute("""
                    INSERT INTO stock_trackings 
                    (decision_date, code, name, rank, score, direction, buy_date, buy_price,
                     t0_close, t0_return, t1_date, t1_close, t1_return,
                     t3_date, t3_close, t3_return, t5_date, t5_close, t5_return,
                     max_gain_5d, max_loss_5d, win_loss_status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(decision_date, code) DO UPDATE SET
                        rank = excluded.rank,
                        score = excluded.score,
                        direction = excluded.direction,
                        buy_date = excluded.buy_date,
                        buy_price = excluded.buy_price,
                        t0_close = excluded.t0_close,
                        t0_return = excluded.t0_return,
                        t1_date = excluded.t1_date,
                        t1_close = excluded.t1_close,
                        t1_return = excluded.t1_return,
                        t3_date = excluded.t3_date,
                        t3_close = excluded.t3_close,
                        t3_return = excluded.t3_return,
                        t5_date = excluded.t5_date,
                        t5_close = excluded.t5_close,
                        t5_return = excluded.t5_return,
                        max_gain_5d = excluded.max_gain_5d,
                        max_loss_5d = excluded.max_loss_5d,
                        win_loss_status = excluded.win_loss_status,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    decision_date, code, name, rank, score, direction, buy_date, buy_price,
                    t0_close, t0_return, t1_date, t1_close, t1_return,
                    t3_date, t3_close, t3_return, t5_date, t5_close, t5_return,
                    max_gain_5d, max_loss_5d, win_loss_status
                ))
                updated_count += 1
                
        conn.commit()
        conn.close()
        
        print(f"[TRACKER] 复盘同步完成！成功跟踪处理 {updated_count}/{processed_count} 只历史精选标的。")
        return {"processed": processed_count, "updated": updated_count}

    @classmethod
    def get_summary_stats(cls, limit: int = 100) -> dict:
        """获取全量与近期胜率统计指标"""
        cls.init_db()
        conn = sqlite3.connect(Config.DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT win_loss_status, max_gain_5d, max_loss_5d, t0_return, t1_return, t3_return, t5_return, rank, direction
            FROM stock_trackings
            ORDER BY decision_date DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return {"total": 0, "win_rate": 0, "avg_max_gain": 0, "avg_max_loss": 0}
            
        total = len(rows)
        win_count = sum(1 for r in rows if r[0] == "WIN")
        loss_count = sum(1 for r in rows if r[0] == "LOSS")
        draw_count = sum(1 for r in rows if r[0] == "DRAW")
        pending_count = sum(1 for r in rows if r[0] == "PENDING")
        
        valid_records = [r for r in rows if r[0] in ("WIN", "LOSS", "DRAW")]
        valid_total = len(valid_records) if valid_records else 1
        
        win_rate = round(win_count / valid_total * 100, 1)
        
        gains = [r[1] for r in rows if r[1] is not None]
        losses = [r[2] for r in rows if r[2] is not None]
        
        avg_max_gain = round(sum(gains) / len(gains), 2) if gains else 0.0
        avg_max_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
        
        # 按排名细分胜率
        rank_stats = {}
        for rank_num in (1, 2, 3):
            r_records = [r for r in valid_records if r[7] == rank_num]
            r_wins = sum(1 for r in r_records if r[0] == "WIN")
            rank_stats[f"Top_{rank_num}"] = {
                "total": len(r_records),
                "wins": r_wins,
                "win_rate": round(r_wins / len(r_records) * 100, 1) if r_records else 0.0
            }
            
        return {
            "total": total,
            "valid_total": len(valid_records),
            "win_count": win_count,
            "loss_count": loss_count,
            "draw_count": draw_count,
            "pending_count": pending_count,
            "win_rate": win_rate,
            "avg_max_gain": avg_max_gain,
            "avg_max_loss": avg_max_loss,
            "rank_stats": rank_stats
        }

    @classmethod
    def get_recent_feedback_text(cls, current_date: str, days: int = 3) -> str:
        """
        生成注入大模型 Prompt 的【实战后效与胜率反馈文本】 (Feedback Loop)
        让大模型清晰了解近期推荐标的的真实走势，指导今日决策。
        """
        cls.init_db()
        conn = sqlite3.connect(Config.DB_PATH)
        cursor = conn.cursor()
        
        # 严格比对日期格式
        if len(current_date) == 8 and current_date.isdigit():
            compare_date = f"{current_date[:4]}-{current_date[4:6]}-{current_date[6:]}"
        else:
            compare_date = current_date
            
        # 找出当前运行日期之前的最近 N 个决策日期
        cursor.execute("""
            SELECT DISTINCT decision_date FROM stock_trackings 
            WHERE decision_date < ? 
            ORDER BY decision_date DESC LIMIT ?
        """, (compare_date, days))
        date_rows = cursor.fetchall()
        
        if not date_rows:
            conn.close()
            return "【近期实战跟踪反馈】：暂无此前交易日的跟踪样本。\n"
            
        target_dates = [r[0] for r in date_rows]
        
        feedback_lines = []
        feedback_lines.append("### 🎯 近期历史推荐实盘跟踪与表现复盘（后效反馈闭环）：")
        feedback_lines.append("> **系统提示**：以下是你在最近几个交易日推荐的 Top 3 标的在真实市场中的后续走势。请认真总结哪些题材方向走出了高胜率与大波段，哪些题材存在冲高回落，并将复盘结论运用于今日的选股打分中：\n")
        
        for d in reversed(target_dates):
            cursor.execute("""
                SELECT rank, code, name, score, direction, buy_price, t0_return, t1_return, max_gain_5d, max_loss_5d, win_loss_status
                FROM stock_trackings
                WHERE decision_date = ?
                ORDER BY rank ASC
            """, (d,))
            records = cursor.fetchall()
            
            feedback_lines.append(f"**📅 决策日期: {d}**")
            for r in records:
                rank, code, name, score, direction, buy_price, t0_ret, t1_ret, max_gain, max_loss, status = r
                status_icon = "🟢 [超预期冲高]" if status == "WIN" else ("🔴 [回撤走弱]" if status == "LOSS" else "🟡 [震荡蓄势]")
                
                t0_str = f"买入当日收盘: {t0_ret:+.2f}%" if t0_ret is not None else ""
                t1_str = f"次日收盘: {t1_ret:+.2f}%" if t1_ret is not None else ""
                gain_str = f"5日最高冲高: +{max_gain:.2f}%" if max_gain is not None else ""
                loss_str = f"5日最大回撤: {max_loss:.2f}%" if max_loss is not None else ""
                
                feedback_lines.append(
                    f"- **Rank {rank} · {name} ({code})** | 方向: {direction} | 评分: {score} | {status_icon}\n"
                    f"  - 实盘走势: {t0_str}, {t1_str}, {gain_str}, {loss_str}"
                )
            feedback_lines.append("")
            
        conn.close()
        return "\n".join(feedback_lines)

if __name__ == "__main__":
    print("=== 开始运行湖滨四季选股历史持续跟踪与自动复盘引擎 ===")
    sync_res = StockTracker.sync_all_decisions()
    print("\n=== 历史选股战法表现统计 ===")
    stats = StockTracker.get_summary_stats()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    
    print("\n=== 生成最近反馈提示词示例 ===")
    feedback = StockTracker.get_recent_feedback_text("2026-08-25", days=3)
    print(feedback)
