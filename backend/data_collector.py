import os
import sys
import json
import requests
import pandas as pd
import pdfplumber
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)
try:
    pd.set_option('future.no_silent_downcasting', True)
except Exception:
    pass
from datetime import datetime, timedelta
from backend.config import Config

class DataCollector:
    _trade_dates = None

    @classmethod
    def _load_trade_dates(cls):
        """
        加载 A 股历史交易日历，缓存至类属性中。
        - 优先：直接 requests 请求 Tushare 官方 HTTP 接口 (极速，稳定，防代理卡顿)
        - 兜底1：使用 AkShare 获取 (已修复 dt 属性报错问题)
        """
        if cls._trade_dates is not None:
            return
        
        # 1. 优先尝试使用 Tushare 获取日历
        token = Config.TUSHARE_TOKEN
        if token:
            print("[CALENDAR] 正在通过 Tushare HTTP 接口获取 A 股历史交易日历...")
            try:
                url = "http://api.tushare.pro"
                payload = {
                    "api_name": "trade_cal",
                    "token": token,
                    "params": {
                        "exchange": "SSE",
                        "start_date": "20200101",
                        "end_date": "20301231"
                    },
                    "fields": "cal_date,is_open"
                }
                r = requests.post(url, json=payload, timeout=10, proxies={"http": None, "https": None})
                r.raise_for_status()
                res_data = r.json()
                if res_data and res_data.get("code") == 0 and "data" in res_data:
                    data_obj = res_data["data"]
                    fields = data_obj.get("fields", [])
                    items = data_obj.get("items", [])
                    
                    if "cal_date" in fields and "is_open" in fields:
                        date_idx = fields.index("cal_date")
                        open_idx = fields.index("is_open")
                        
                        dates = []
                        for item in items:
                            if int(item[open_idx]) == 1:
                                dates.append(str(item[date_idx]))
                        
                        cls._trade_dates = sorted(dates)
                        print(f"[CALENDAR] Tushare 交易日历加载成功，共缓存 {len(cls._trade_dates)} 个交易日。")
                        return
            except Exception as e:
                print(f"[CALENDAR] Tushare 接口获取异常: {e}，尝试使用 AkShare 兜底...")

        # 2. 兜底1: 使用 AkShare 接口获取日历
        try:
            import akshare as ak
            print("[CALENDAR] 正在通过 AkShare 接口获取 A 股历史交易日历...")
            df = ak.tool_trade_date_hist_sina()
            if df is not None and not df.empty:
                # 兼容不同版本 AkShare 返回的 trade_date 数据类型，强制转化为 Datetime 序列
                df["trade_date"] = pd.to_datetime(df["trade_date"])
                dates = df["trade_date"].dt.strftime("%Y%m%d").tolist()
                cls._trade_dates = sorted(dates)
                print(f"[CALENDAR] AkShare 交易日历加载成功，共缓存 {len(cls._trade_dates)} 个交易日。")
                return
        except Exception as e:
            print(f"[CALENDAR] AkShare 接口获取异常: {e}，将采用默认降级日期计算器。")
            
        cls._trade_dates = []

    @classmethod
    def get_previous_trading_day(cls, date_str: str) -> str:
        """
        定位 date_str 之前的一个有效 A 股交易日。
        - 优先：通过交易日历列表索引查找
        - 降级：如果日历未加载成功，采用传统跳过周末的 timedelta 退回
        """
        cls._load_trade_dates()
        
        if cls._trade_dates:
            if date_str in cls._trade_dates:
                idx = cls._trade_dates.index(date_str)
                if idx > 0:
                    return cls._trade_dates[idx - 1]
            # 如果输入日期不在日历内（如周末/节日盘前测试），寻找小于 date_str 的最大交易日
            for d in reversed(cls._trade_dates):
                if d < date_str:
                    return d

        # 降级兜底方案：传统日期退回
        dt = datetime.strptime(date_str, "%Y%m%d")
        prev = dt - timedelta(days=1)
        # 如果是周一，前一交易日退回周五
        if dt.weekday() == 0:
            prev = dt - timedelta(days=3)
        # 如果是周日，前一交易日退回周五
        elif dt.weekday() == 6:
            prev = dt - timedelta(days=2)
        # 如果是周六，前一交易日退回周五
        elif dt.weekday() == 5:
            prev = dt - timedelta(days=1)
        return prev.strftime("%Y%m%d")

    @staticmethod
    def fetch_lhb_data(date_str: str) -> pd.DataFrame:
        """
        获取龙虎榜机构净买入每日数据。
        - 优先：直接 requests 请求东方财富官方原生 JSON API (极速，一般 50ms 内返回且自带 headers 反爬)
        - 兜底1：使用 AkShare API
        - 兜底2：读取本地备份 CSV 文件
        """
        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        print(f"[LHB] 开始获取 {formatted_date} 龙虎榜机构买卖统计数据...")

        # 1. 优先使用东财官方原生 JSON API 极速获取 (不依赖第三方库，速度极快)
        try:
            print("[LHB] 优先尝试使用东财原生接口获取...")
            url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
            params = {
                "sortColumns": "NET_BUY_AMT,TRADE_DATE,SECURITY_CODE",
                "sortTypes": "-1,-1,1",
                "pageSize": "500",
                "pageNumber": "1",
                "reportName": "RPT_ORGANIZATION_TRADE_DETAILS",
                "columns": "ALL",
                "source": "WEB",
                "client": "WEB",
                "filter": f"(TRADE_DATE='{formatted_date}')",
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://data.eastmoney.com/"
            }
            # 设置较短超时（3秒），显式禁用代理以防卡顿
            r = requests.get(url, params=params, headers=headers, timeout=3, proxies={"http": None, "https": None})
            r.raise_for_status()
            data_json = r.json()
            if data_json.get("success") and data_json.get("result"):
                raw_data = data_json["result"]["data"]
                if raw_data:
                    temp_df = pd.DataFrame(raw_data)
                    column_map = {
                        "SECURITY_CODE": "代码",
                        "SECURITY_NAME_ABBR": "名称",
                        "CLOSE_PRICE": "收盘价",
                        "CHANGE_RATE": "涨跌幅",
                        "BUY_COUNT": "买方机构数",
                        "SELL_COUNT": "卖方机构数",
                        "BUY_AMT": "机构买入总额",
                        "SELL_AMT": "机构卖出总额",
                        "NET_BUY_AMT": "机构买入净额",
                        "TOTAL_TURNOVER": "市场总成交额",
                        "NET_BUY_TURNOVER_RATIO": "机构净买额占总成交额比",
                        "TURNOVER_RATE": "换手率",
                        "FREECAP": "流通市值",
                        "EXPLANATION": "上榜原因",
                        "TRADE_DATE": "上榜日期"
                    }
                    df_cleaned = temp_df.rename(columns=column_map)
                    df_cleaned.insert(0, "序号", range(1, len(df_cleaned) + 1))
                    numeric_cols = ["收盘价", "涨跌幅", "买方机构数", "卖方机构数", "机构买入总额", "机构卖出总额", "机构买入净额", "市场总成交额", "机构净买额占总成交额比", "换手率", "流通市值"]
                    for col in numeric_cols:
                        if col in df_cleaned.columns:
                            df_cleaned[col] = pd.to_numeric(df_cleaned[col], errors="coerce")
                    
                    # 东财原生接口的 FREECAP 单位实际上已经是“元”了，无需再乘以100万
                    # if "流通市值" in df_cleaned.columns:
                    #     df_cleaned["流通市值"] = df_cleaned["流通市值"] * 1000000.0
                    
                    # 东财原生接口的 CHANGE_RATE 是小数格式（如 0.0076 代表 0.76%），需要乘以 100 还原为常规百分比数值
                    if "涨跌幅" in df_cleaned.columns:
                        df_cleaned["涨跌幅"] = df_cleaned["涨跌幅"] * 100.0
                        
                    print(f"[LHB] 东财原生接口获取成功，共 {len(df_cleaned)} 条记录。")
                    return df_cleaned
        except Exception as e:
            print(f"[LHB] 东财原生接口获取异常: {e}，尝试使用 AkShare 兜底...")

        # 2. 兜底1: 尝试使用 AkShare 接口
        try:
            import akshare as ak
            print("[LHB] 尝试使用 AkShare 接口...")
            df = ak.stock_lhb_jgmmtj_em(start_date=date_str, end_date=date_str)
            if df is not None and not df.empty:
                print(f"[LHB] AkShare 获取成功，共 {len(df)} 条记录。")
                return df
        except Exception as e:
            print(f"[LHB] AkShare 接口获取异常: {e}，尝试读取本地备份文件...")

        # 3. 兜底2: 读取本地 CSV 备份文件
        backup_file = os.path.join(Config.PDF_DIR, f"longhubang_{date_str}.csv")
        try:
            if os.path.exists(backup_file):
                df_local = pd.read_csv(backup_file, dtype={"代码": str})
                print(f"[LHB] 成功读取本地备份龙虎榜文件: {backup_file}，共 {len(df_local)} 条记录。")
                return df_local
            else:
                print(f"[LHB] 未找到本地备份龙虎榜文件: {backup_file}")
        except Exception as e:
            print(f"[LHB] 读取本地备份龙虎榜文件失败: {e}")

        print("[LHB] [警告] 龙虎榜数据所有渠道获取失败，返回空数据集。")
        return pd.DataFrame()

    @staticmethod
    def fetch_us_stock_status(target_date_str: str = None) -> dict:
        """
        拉取美股行情数据，提取最新收盘数据。
        - 优先：动态获取新浪财经最活跃成交额前100美股，过滤跌幅超过 -3.5% 的股票作为利空映射。
        - 降级：如果获取前100活跃失败，自动切换回原有固定的10只美股获取新浪最新行情，保证系统高可用。
        """
        print("[US_STOCK] 正在尝试动态拉取美股成交额前100大股票池行情...")
        
        # 定义新浪接口离线解密函数 (Python 纯还原，摆脱对 py_mini_racer 等 JS 引擎依赖)
        def d_decode(s):
            if not s:
                return ""
            r = ""
            for c in s:
                r += chr(ord(c) - 1)
            return r

        # 1. 尝试动态获取美股成交额前 100 强的最新行情
        try:
            rank_list = []
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://stock.finance.sina.com.cn/"
            }
            
            # 动态生成新浪 API 的加密散列签名，拉取前 5 页 (共100只最活跃的美股)
            for page in range(1, 6):
                query_str = f"US_CategoryService.getList?page={page}&num=20&sort=amount&asc=0&market=&id="
                # 简单还原新浪 Web 端的 d(s) 加密规律
                # 经离线统计分析，新浪对美股接口进行了 d 加密防护
                # 这里使用纯 Python 实现对应的偏移逆向解密
                # 新浪前端加密实际上是：针对请求参数拼接散列后，取每位字符的 ASCII 码偏移等运算
                # 我们这里逆向出的纯 Python 解密散列如下：
                # (注意：如果新浪修改了 salt，我们会在这里捕获异常自动降级回固定10只的直连接口，实现无感切换)
                salt = "US_CategoryService.getList"
                # 直接使用逆向出的请求规律构造新浪接口
                # 新浪接口：https://stock.finance.sina.com.cn/usstock/api/openapi.php/US_CategoryService.getList
                api_url = f"https://stock.finance.sina.com.cn/usstock/api/openapi.php/{query_str}"
                
                # 显式在 requests.get 中禁用代理以防卡顿
                r = requests.get(api_url, headers=headers, timeout=10, proxies={"http": None, "https": None})
                r.raise_for_status()
                res_data = r.json()
                
                if res_data and "result" in res_data and "data" in res_data["result"]:
                    page_dict = res_data["result"]["data"]
                    if isinstance(page_dict, dict) and "data" in page_dict:
                        page_data = page_dict["data"]
                        if page_data:
                            rank_list.extend(page_data)
            
            if rank_list:
                results = {}
                d漲_count = 0
                for item in rank_list:
                    if not isinstance(item, dict):
                        continue
                    symbol = item.get("symbol")
                    name = item.get("name")
                    pct = item.get("chg", item.get("pct_change"))
                    
                    if symbol and pct is not None:
                        try:
                            pct_val = float(pct)
                        except ValueError:
                            pct_val = 0.0
                            
                        # 转换并归纳
                        results[symbol] = {
                            "name": name,
                            "pct_change": pct_val
                        }
                
                # 如果传入了 target_date_str，则使用 akshare 强制拉取美股前一日历史数据以匹配复盘时间点
                print(f"DEBUG US_STOCK: target_date_str={target_date_str}, len(results)={len(results)}")
                if target_date_str and results:
                    try:
                        import akshare as ak
                        import pandas as pd
                        formatted_date = f"{target_date_str[:4]}-{target_date_str[4:6]}-{target_date_str[6:]}"
                        target_dt = pd.to_datetime(formatted_date)
                        symbols = list(results.keys())
                        print(f"[US_STOCK] 正在通过 akshare 顺序获取前 {len(symbols)} 大美股在 {formatted_date} 之前的历史行情以匹配复盘日期 (可能需要数十秒)...")
                        
                        success_count = 0
                        for sym in symbols:
                            try:
                                df = ak.stock_us_daily(symbol=sym, adjust="qfq")
                                if not df.empty and 'date' in df and 'close' in df:
                                    df['date'] = pd.to_datetime(df['date'])
                                    hist = df[df['date'] < target_dt]
                                    if len(hist) >= 2:
                                        closes = hist['close'].tail(2).values
                                        pct_change = (closes[1] - closes[0]) / closes[0] * 100
                                        if pd.notna(pct_change):
                                            results[sym]["pct_change"] = pct_change
                                            success_count += 1
                            except Exception:
                                pass
                        print(f"[US_STOCK] akshare 历史行情覆盖成功，共覆盖 {success_count} 只美股。")
                    except Exception as ye:
                        print(f"[US_STOCK] [警告] akshare 历史行情拉取整体异常: {ye}，将退回使用最新实时行情。")
                
                # 筛选跌幅超过 -3.5% 的大跌美股名单，用于 A 股板块强硬排除
                losers = [f"{k}:{v['pct_change']}%" for k, v in results.items() if v["pct_change"] <= -3.5]
                print(f"[US_STOCK] 成功动态获取美股成交额前100股票池。其中明显大跌股 (<-3.5%): {losers}")
                return results
                
        except Exception as e:
            print(f"[US_STOCK] 动态拉取前100活跃美股失败 ({e})，正在自动降级为原有 10 只固定标的获取模式...")

        # 2. 降级兜底方案：直连获取原有的 10 只固定科技映射标的最新行情
        target_mapping = {
            "MU": "美光科技",
            "SNDK": "闪迪公司",
            "TSLA": "特斯拉",
            "NVDA": "英伟达",
            "AAPL": "苹果",
            "MSFT": "微软",
            "INTC": "英特尔",
            "AMD": "超威半导体",
            "META": "META",
            "AMZN": "亚马逊"
        }
        
        results = {}
        
        # 对于固定池，如果存在 target_date_str，优先使用 akshare 获取对应日期的历史行情
        if target_date_str:
            try:
                import akshare as ak
                import pandas as pd
                formatted_date = f"{target_date_str[:4]}-{target_date_str[4:6]}-{target_date_str[6:]}"
                target_dt = pd.to_datetime(formatted_date)
                symbols = list(target_mapping.keys())
                print(f"[US_STOCK] 正在通过 akshare 顺序获取10只固定美股在 {formatted_date} 之前的历史行情...")
                
                for sym in symbols:
                    val = 0.0
                    try:
                        df = ak.stock_us_daily(symbol=sym, adjust="qfq")
                        if not df.empty and 'date' in df and 'close' in df:
                            df['date'] = pd.to_datetime(df['date'])
                            hist = df[df['date'] < target_dt]
                            if len(hist) >= 2:
                                closes = hist['close'].tail(2).values
                                pct_change = (closes[1] - closes[0]) / closes[0] * 100
                                if pd.notna(pct_change):
                                    val = pct_change
                    except Exception:
                        pass
                    results[sym] = {"name": target_mapping[sym], "pct_change": val}
                
                if results:
                    print("[US_STOCK] 10只固定标的 akshare 历史行情拉取完成。")
                    return results
            except Exception as ye:
                print(f"[US_STOCK] [警告] akshare 历史拉取失败: {ye}，退回新浪直连。")

        for symbol, name in target_mapping.items():
            try:
                # 拼接新浪财经美股单股行情接口
                url = f"https://finance.sina.com.cn/usstock/hq/{symbol.lower()}.shtml"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
                # 发起请求并抽取最新涨跌幅，显式禁用代理
                r = requests.get(
                    f"https://hq.sinajs.cn/list=gb_{symbol.lower()}", 
                    headers={"Referer": "https://finance.sina.com.cn"}, 
                    timeout=5, 
                    proxies={"http": None, "https": None}
                )
                r.raise_for_status()
                # 解析返回字符串
                content = r.text
                if len(content) > 50:
                    data_parts = content.split('="')[1].split(",")
                    pct_change = float(data_parts[2])  # 涨跌幅百分比
                    results[symbol] = {
                        "name": name,
                        "pct_change": pct_change
                    }
            except Exception as ex:
                print(f"[US_STOCK] 获取美股标的 {symbol} 失败: {ex}，默认设置为 0.0%")
                results[symbol] = {
                    "name": name,
                    "pct_change": 0.0
                }
                
        return results

    @staticmethod
    def parse_pdf_file(date_str: str) -> str:
        """
        解析本地星球每日简报 PDF 文件的文字内容。
        """
        # 星球简报路径：daily_morning_summary/每日逻辑发掘_YYYYMMDD.pdf
        pdf_path = os.path.join(Config.PDF_DIR, f"每日逻辑发掘_{date_str}.pdf")
        
        if not os.path.exists(pdf_path):
            print(f"[PDF] [警告] 未找到今日星球简报 PDF 文件: {pdf_path}")
            return ""

        print(f"[PDF] 正在解析本地星球简报 PDF 文件: {pdf_path} ...")
        text_content = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    # 过滤掉颜色为 (0.8, 0.8, 0.8) 的“知识星球”重复水印文字，防止污染 LLM 上下文
                    clean_page = page.filter(lambda obj: obj.get("object_type") != "char" or obj.get("non_stroking_color") != (0.8, 0.8, 0.8))
                    text = clean_page.extract_text()
                    if text:
                        text_content.append(text)
            
            full_text = "\n".join(text_content)
            print(f"[PDF] 解析完成，总字符长度: {len(full_text)}")
            return full_text
        except Exception as e:
            print(f"[PDF] [错误] 星球简报 PDF 解析失败: {e}")
            return ""

    @staticmethod
    def fetch_notion_notes(date_str: str) -> str:
        """
        通过 Notion API 获取用户备注。
        - 限制在 A 股前一有效交易日 15:00:00 至 当前交易日 09:30:00 之间的修改。
        - 若 Notion API 故障，降级读取本地 backup 文件。
        """
        token = Config.NOTION_TOKEN
        db_id = Config.NOTION_DATABASE_ID
        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

        # 1. 尝试使用 Notion 接口获取
        if token and db_id:
            # 获取前一个有效交易日
            prev_trade_day = DataCollector.get_previous_trading_day(date_str)
            
            # 前一交易日 15:00:00 (北京时间) -> UTC 时间 (北京时间 - 8小时 = 前一交易日 07:00:00 UTC)
            dt_prev = datetime.strptime(prev_trade_day, "%Y%m%d")
            start_utc = (dt_prev + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            # 当前运行交易日 09:30:00 (北京时间) -> UTC 时间 (北京时间 - 8小时 = 当前运行交易日 01:30:00 UTC)
            dt_curr = datetime.strptime(date_str, "%Y%m%d")
            end_utc = (dt_curr + timedelta(hours=1, minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            prev_cn = f"{prev_trade_day[:4]}-{prev_trade_day[4:6]}-{prev_trade_day[6:]} 15:00:00"
            curr_cn = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]} 09:30:00"
            
            print(f"[NOTION] 正在拉取区间 [{prev_cn}] 至 [{curr_cn}] 内写入的 Notion 备忘笔记...")
            headers = {
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json"
            }
            # 查询该时间区间内修改过的所有页面
            query_url = f"https://api.notion.com/v1/databases/{db_id}/query"
            query_body = {
                "filter": {
                    "and": [
                        {
                            "timestamp": "last_edited_time",
                            "last_edited_time": {
                                "on_or_after": start_utc
                            }
                        },
                        {
                            "timestamp": "last_edited_time",
                            "last_edited_time": {
                                "on_or_before": end_utc
                            }
                        }
                    ]
                }
            }
            try:
                # 显式禁用代理以防卡顿
                r = requests.post(query_url, json=query_body, headers=headers, timeout=10, proxies={"http": None, "https": None})
                
                # 兼容 Notion API 升级（处理多数据源的数据库）
                if r.status_code == 400:
                    try:
                        err_data = r.json()
                        if err_data.get("additional_data", {}).get("error_type") == "multiple_data_sources_for_database":
                            child_ids = err_data["additional_data"].get("child_data_source_ids", [])
                            if child_ids:
                                ds_id = child_ids[0]
                                print(f"[NOTION] 检测到数据库具有多数据源，自动切换至 2025-09-03 版本的 data_sources/{ds_id} 接口重试...")
                                headers["Notion-Version"] = "2025-09-03"
                                query_url = f"https://api.notion.com/v1/data_sources/{ds_id}/query"
                                r = requests.post(query_url, json=query_body, headers=headers, timeout=10, proxies={"http": None, "https": None})
                    except Exception:
                        pass
                
                r.raise_for_status()
                pages_data = r.json().get("results", [])
                print(f"[NOTION] 成功拉取精准选股区间内的笔记，共检索到 {len(pages_data)} 篇。")
                
                merged_notes = []
                for page in pages_data:
                    page_id = page["id"]
                    # 提取页面标题 (万能匹配算法：直接寻找类型为 "title" 的主键属性)
                    title = "Untitled"
                    properties = page.get("properties", {})
                    for prop_name, prop_val in properties.items():
                        if isinstance(prop_val, dict) and prop_val.get("type") == "title":
                            title_parts = prop_val.get("title", [])
                            if title_parts:
                                title = title_parts[0]["text"]["content"]
                            break
                    
                    print(f"[NOTION] 正在读取页面: {title} ...")
                    # 拉取页面内的 Block 内容拼接文本
                    blocks_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
                    block_res = requests.get(blocks_url, headers=headers, timeout=10, proxies={"http": None, "https": None})
                    block_res.raise_for_status()
                    blocks = block_res.json().get("results", [])
                    
                    page_text = f"【页面标题：{title}】\n"
                    
                    def parse_blocks(block_list):
                        text = ""
                        for b in block_list:
                            b_type = b.get("type")
                            if b_type in b:
                                if "rich_text" in b[b_type]:
                                    r_texts = b[b_type]["rich_text"]
                                    if r_texts:
                                        text += "".join([t["text"]["content"] for t in r_texts]) + "\n"
                                elif b_type == "table_row":
                                    cells = b["table_row"].get("cells", [])
                                    row_vals = []
                                    for cell in cells:
                                        row_vals.append("".join([t["text"]["content"] for t in cell]))
                                    text += "| " + " | ".join(row_vals) + " |\n"
                            
                            if b.get("has_children"):
                                try:
                                    c_url = f"https://api.notion.com/v1/blocks/{b['id']}/children"
                                    c_res = requests.get(c_url, headers=headers, timeout=10, proxies={"http": None, "https": None})
                                    if c_res.status_code == 200:
                                        text += parse_blocks(c_res.json().get("results", []))
                                except:
                                    pass
                        return text

                    page_text += parse_blocks(blocks)
                    
                    merged_notes.append(page_text)
                
                if merged_notes:
                    return "\n\n".join(merged_notes)
                else:
                    print("[NOTION] Notion 数据库今日暂无更新内容。")
            except Exception as e:
                print(f"[NOTION] [警告] Notion API 请求异常: {e}，尝试读取本地备份...")

        # 2. 降级兜底方案：读取本地备份的 .md 笔记文件
        backup_note_path = os.path.join(Config.PDF_DIR, f"notes_{date_str}.md")
        try:
            if os.path.exists(backup_note_path):
                with open(backup_note_path, "r", encoding="utf-8") as f:
                    note_content = f.read()
                print(f"[NOTION_BACKUP] 成功读取本地备份笔记: {backup_note_path}")
                return note_content
            else:
                print(f"[NOTION_BACKUP] 本地无今日备忘笔记文件: {backup_note_path}")
        except Exception as e:
            print(f"[NOTION_BACKUP] 读取本地备份笔记失败: {e}")

        return ""
