import os
import json
import requests
import re
import pandas as pd
from backend.config import Config

class DecisionEngine:
    @classmethod
    def _repair_json_string(cls, raw_str: str) -> str:
        """
        智能自愈修复大模型返回的 JSON：
        - 将 JSON 字符串内部未转义的双引号进行自动转义，规避 SyntaxError。
        """
        lines = raw_str.split("\n")
        repaired_lines = []
        for line in lines:
            stripped = line.strip()
            # 匹配 "key": "value" 结构 (兼容逗号和无逗号)
            match = re.match(r'^"([^"]+)":\s*"(.*)"(,?)$', stripped)
            if match:
                key = match.group(1)
                val = match.group(2)
                suffix = match.group(3)
                
                # 剔除 val 内部已合法转义的 \"
                temp_val = val.replace('\\"', '___DOUBLE_QUOTE_PLACEHOLDER___')
                # 将剩余的所有未转义英文双引号替换为 \"
                temp_val = temp_val.replace('"', '\\"')
                # 恢复之前本就合法的转义双引号
                clean_val = temp_val.replace('___DOUBLE_QUOTE_PLACEHOLDER___', '\\"')
                
                # 保留原有的行缩进
                indent = line[:len(line) - len(stripped)]
                repaired_lines.append(f'{indent}"{key}": "{clean_val}"{suffix}')
            else:
                repaired_lines.append(line)
        return "\n".join(repaired_lines)
    @classmethod
    def _call_llm(cls, system_prompt: str, user_prompt: str) -> str:
        """
        调用大模型 API。支持 OpenAI 兼容 API 以及本地 Ollama。
        """
        headers = {
            "Authorization": f"Bearer {Config.LLM_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # 组装请求参数
        is_openrouter = "openrouter.ai" in Config.LLM_API_BASE.lower()
        is_zhipu_official = "bigmodel.cn" in Config.LLM_API_BASE.lower()
        
        data = {
            "model": Config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": True,
            "temperature": 1.0,
            "max_tokens": 131072,
        }

        # 平台差异化推理参数
        if is_zhipu_official:
            # 智谱官方：thinking + tool_stream + reasoning_effort
            data["thinking"] = {"type": "enabled"}
            data["tool_stream"] = True
            data["reasoning_effort"] = "medium"
        elif is_openrouter:
            # OpenRouter：根据模型传入不同的 reasoning 格式
            if "kimi" in Config.LLM_MODEL.lower():
                data["reasoning"] = {
                    "enabled": True
                }
            else:
                data["reasoning"] = {
                    "effort": "medium",
                    "exclude": False    # 保留推理过程，方便调试和日志记录
                }

        # 尝试开启联网搜索工具
        if is_openrouter:
            data["tools"] = [
                {
                    "type": "openrouter:web_search"
                }
            ]
        elif is_zhipu_official and "glm" in Config.LLM_MODEL.lower():
            data["tools"] = [
                {
                    "type": "web_search",
                        "web_search": {
                            "enable": True,
                            "search_engine": "search_pro_sogou",
                            "search_intent": False,
                            "search_recency_filter": "oneWeek",
                            "content_size": "high",
                            "count": 20
                        }
                    }
                ]

        # 如果是 Ollama，可以不加 Authorization Header
        if "localhost" in Config.LLM_API_BASE or "127.0.0.1" in Config.LLM_API_BASE:
            headers.pop("Authorization", None)
            data.pop("tools", None)
            data.pop("plugins", None)

        url = f"{Config.LLM_API_BASE.rstrip('/')}/chat/completions"
        print(f"[LLM] 正在请求大模型 API ({Config.LLM_MODEL})...")
        if "tools" in data or "plugins" in data:
            print("[LLM] 联网搜索功能已在 API 侧开启。")
        
        session = requests.Session()
        max_retries = 3
        last_exception = None
        
        for attempt in range(1, max_retries + 1):
            response = None
            try:
                data["stream"] = True
                print("[LLM] 开启流式输出 (Stream) 模式，准备实时接收思考与推理过程...")
                
                # 显式禁用系统代理以防代理断流，由 session 复用 TCP 连接以减少 Cold Start 时延
                response = session.post(url, json=data, headers=headers, timeout=1200, proxies={"http": None, "https": None}, stream=True)
                response.raise_for_status()
                
                full_content = ""
                full_reasoning = ""
                
                print("\n==================== LLM 推理与输出 ====================")
                for line in response.iter_lines():
                    if line:
                        line = line.decode('utf-8')
                        
                        # OpenRouter 会发送 SSE 心跳注释行 (以冒号开头) 来防止连接超时，直接跳过
                        if line.startswith(":"):
                            continue
                        
                        if line.startswith("data: ") and line != "data: [DONE]":
                            try:
                                chunk = json.loads(line[6:])
                                
                                # 拦截并暴露 OpenRouter 返回的流式异常
                                if "error" in chunk:
                                    err_msg = chunk["error"].get("message", str(chunk["error"]))
                                    print(f"\n[LLM] 服务端在流式返回中报告严重错误: {err_msg}")
                                    raise RuntimeError(f"Stream Error: {err_msg}")
                                
                                choices = chunk.get("choices", [])
                                # OpenRouter 在流尾部会发一个 choices 为空的 usage-only chunk，跳过
                                if not choices:
                                    continue
                                    
                                delta = choices[0].get("delta", {})
                                
                                # 提取并实时打印思考过程 (灰色显示)
                                reasoning = delta.get("reasoning_content", "")
                                if not reasoning:
                                    reasoning = delta.get("reasoning", "") # 兼容部分模型使用 reasoning 字段
                                if reasoning:
                                    full_reasoning += reasoning
                                    print(f"\033[90m{reasoning}\033[0m", end='', flush=True)
                                
                                # 提取并实时打印最终文本
                                text = delta.get("content", "")
                                if text:
                                    full_content += text
                                    try:
                                        print(text, end='', flush=True)
                                    except UnicodeEncodeError:
                                        # 规避 Windows 控制台输出 emoji 导致崩溃
                                        print(text.encode('gbk', 'ignore').decode('gbk'), end='', flush=True)
                            except RuntimeError as re:
                                raise re
                            except Exception:
                                pass
                
                print("\n==================== 结束 ====================")
                
                content = full_content.strip()
                # 鲁棒性提取：找到真正的 JSON 起止边界
                start_idx = content.find('{')
                end_idx = content.rfind('}')
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    content = content[start_idx:end_idx+1]
                return content
            except Exception as e:
                last_exception = e
                print(f"[LLM] 第 {attempt}/{max_retries} 次请求失败: {e}")
                
                # 降级逻辑：如果是因为 tools 参数不支持，在重试前强行移除 tools
                if "tools" in data:
                    print("[LLM] [降级提示] 联网搜索 API 请求失败，可能是中转服务商或此模型端口未开放 web_search。正在自动剔除联网插件重新发起常规请求...")
                    data.pop("tools", None)
                    
                if response is not None:
                    print(f"[LLM] 服务端错误返回详情: {response.text}")
                if attempt < max_retries:
                    import time
                    print("[LLM] 检测到连接重置或网关拦截，正在等待 2 秒以进行 TCP 连接预热与重试...")
                    time.sleep(2)
        
        raise last_exception

    @classmethod
    def build_prompts(cls, date_str: str, pdf_text: str, lhb_df: pd.DataFrame, us_stocks: dict, notion_text: str, history_text: str) -> tuple:
        """
        组装大模型决策所需的 System Prompt 和 User Prompt。
        - 整合美股情绪排除、A股龙虎榜机构席位、星球PDF逻辑、Notion笔记和近3日历史决策。
        """
        # 1. 对龙虎榜个股进行量化过滤与清洗，生成候选股信息文本，降低大模型的上下文噪音
        candidate_list = []
        if lhb_df is not None and not lhb_df.empty:
            for _, row in lhb_df.iterrows():
                code = str(row["代码"])
                name = str(row["名称"])
                net_buy = float(row["机构买入净额"])
                market_cap = float(row["流通市值"])
                net_buy_wan = round(net_buy / 10000, 2)
                market_cap_yi = round(market_cap / 100000000, 2)
                candidate_list.append({
                    "code": code,
                    "name": name,
                    "price": row["收盘价"],
                    "change_pct": row["涨跌幅"],
                    "buy_num": row["买方机构数"],
                    "sell_num": row["卖方机构数"],
                    "net_buy_wan": net_buy_wan,
                    "market_cap_yi": market_cap_yi,
                    "reason": row["上榜原因"]
                })
        
        # 将候选股信息格式化为文本
        candidates_text = ""
        if candidate_list:
            candidates_text = "### A股龙虎榜当日上榜候选个股：\n"
            for c in candidate_list:
                candidates_text += (
                    f"- 代码: {c['code']}, 名称: {c['name']}, 收盘价: {c['price']}元, 涨跌幅: {c['change_pct']}%, "
                    f"买方机构数: {c['buy_num']}, 卖方机构数: {c['sell_num']}, 机构买入净额: {c['net_buy_wan']}万元, "
                    f"流通市值: {c['market_cap_yi']}亿元, 上榜原因: {c['reason']}\n"
                )
        else:
            candidates_text = "今日未通过系统拉取龙虎榜明细，请直接参考【Notion个人备忘】中记录的机构净买入核心标的信息汇总表进行资金面研判。\n"

        # 2. 格式化美股收盘表现文本 (仅筛选最核心的 8 只大盘科技巨头以及跌幅超 -3.5% 的核心利空标的，压缩上下文以避开网关包长度限制)
        us_stocks_text = "### 隔夜美股核心映射板块表现：\n"
        if us_stocks:
            core_tech_symbols = {"NVDA", "AAPL", "TSLA", "MSFT", "GOOGL", "MU", "ASML", "AMZN"}
            filtered_us_stocks = {}
            
            for k, v in us_stocks.items():
                try:
                    pct = float(v["pct_change"])
                except:
                    pct = 0.0
                if k in core_tech_symbols or pct <= -3.5:
                    filtered_us_stocks[k] = v
            
            for k, v in filtered_us_stocks.items():
                us_stocks_text += f"- {k} ({v['name']}): 收盘涨跌幅: {v['pct_change']}%\n"
        else:
            us_stocks_text += "美股行情数据拉取异常，请通过新闻资讯进行基本面研判。\n"

        # 3. 组装系统 System Prompt，明确湖滨四季战法和样例“蒸馏”逻辑
        system_prompt = """你是一个顶级证券投资总监与王牌分析师，熟练运用“湖滨四季战法”进行每日选股。
你的任务是根据盘前提供的美股大盘表现、A股龙虎榜机构数据、知识星球逻辑简报及Notion个人备忘，逻辑极其严密、专业度极高地输出今日的选股报告。

【湖滨四季战法核心与打分金律（从历史标杆样本蒸馏的智慧）】：
0. 语料主次与推理铁律：
   - 【主次分明】：你的所有选股核心逻辑与产业催化，必须以【知识星球《每日逻辑发掘》语料】为主线和基石。【Notion自定义输入备注】仅作为辅助和补充参考材料。当两者信息存在冲突或侧重点不同时，必须以星球语料的研判方向为绝对主导，Notion 备注绝不能喧宾夺主。
   - 【纯中文铁律】：无论检索到的外部资料是何种语言，你**必须且只能使用纯中文（简体）**进行所有的思考推理（Reasoning）与最终输出。严禁在输出中大段生成英文思考过程，以避免浪费 Token 导致报告被截断！
1. 市场环境与战法模式判定（仓位与战法模式动态金律）：
   - 必须优先评估隔夜美股核心科技股（AI硬件、光通信、存储、半导体设备）的表现。
   - 【实时搜索铁律（宏观与微观全覆盖）】：
     * 宏观层面：凡是涉及到今日实时大盘行情、亚太市场动态、A50夜盘收盘、国内重大财经快闻等，必须且只能通过实时联网搜索（web_search）工具获取。
     * 微观层面：对于你最终输出的任何个股的时效性信息（包括但不限于：流通市值、近5日涨跌幅、K线及筹码形态特征、市盈率/基本面最新变化），严禁凭空捏造或依赖离线记忆！你必须调用联网搜索仔细核对这些具体数据，仔细扫描你的输出结果，确保任何需要联网的信息都形成了“搜索验证 -> 结果输出”的逻辑闭环。
   - 【联网降级容错】：如果你的工具箱中未被配置或无法正常使用联网搜索工具，你应本着稳健原则，直接基于我们提供的美股行情、龙虎榜与Notion个人备忘进行研判，且在个股数据（如市值、涨幅）上附带“[待二次校验]”的免责说明。
   - 并在报告综述中自动判定“战法模式”与“总仓位建议”。
   - 模式与仓位配比必须根据以下环境动态决定：
     * 【主动进攻 / 乘胜追击】：外围美股普涨、A50夜盘强势且国内无重大雷点。建议总仓位调高至 50% - 70% 甚至满仓（保留 30% 以下现金），积极进攻主线景气。
     * 【均势博弈 / 择优低吸】：外围震荡走平、A50表现平淡，国内有独立的业绩或题材催化。建议总仓位控制在 30% - 50% 之间（保留 50% 以上现金），重个股轻大盘。
     * 【防守反击 / 现金为王】：外围美股科技板块大幅杀跌、A50夜盘重挫、或国内暴雷利空频发。建议总仓位严格控制在 30% 以下（保留 70% 以上现金），轻仓防守或空仓待机。
2. 铁律排除清单 (Hard Exclusions)：
   - 光通信/CPO：若美股光通信个股出现大跌（跌幅超过4%），则今日A股光模块/CPO概念股必须直接硬排除，规避补跌风险。
   - 存储芯片：若美股存储龙头大跌，则今日A股纯存储概念股必须直接排除。
   - 半导体设备：若费城半导体设备或核心美股设备商重挫，则A股半导体设备股暂不优先，今日排除。
   - 国内重大负面快讯：对于国内重大负面快讯中提及的重大利空个股（如上市公司立案留置、重大控制权变更拟变更、大股东大额减持开启等），今日必须在“重点放弃/排除标的”中坚决予以排除。
3. 战法打分分项体系（总分100分）：
   - 题材催化度（40分）：产业催化密集，属于不受外围杀跌影响的独立景气方向（如人形机器人、苹果折叠屏超预期备货、中报大预增等）。
   - 资金买入力度（30分）：机构净买入越靠前的股票具有越大的资金面打分优势。若个股无大额净买入或遭机构大额净卖出，则该项扣分。若今日未拉取龙虎榜数据，则必须参考【Notion个人备忘】中记录的机构净买入信息进行打分，不得以此无脑扣减资金买入力度评分。
   - 技术筹码面（30分）：K线在21日均线附近企稳温和放量、或呈均线多头排列，底部阳多阴少最佳。高位连板追高扣分，高位补跌风险股排除。
4. 首选三标介入条件与决策连贯性参考：
   - 必须根据个股技术面和筹码的强弱、位置差异，精细化、差异化制定介入条件（竞价开盘跌幅限制、量比要求，以及高开多少追高风险大、低开如何右侧低吸等），切忌千篇一律！
   - 必须阅读并深度参考“近 3 个交易日历史选股决策参考”。若某只个股在前几天已连续被选入首选三标且评分高企，今日除非有新的强力题材支撑，否则不应继续推荐以防短线交易拥挤；同时，利用历史参考保持策略与个股跟踪的连贯性。

【标杆报告格式及排版蒸馏示例】：
生成的 full_markdown_report 报告必须严格遵循以下精美的排版和结构（包含所有的标题、Markdown 表格和细节，其中战法模式与总仓位建议必须由你根据今日的外部环境动态计算得出）：
# 湖滨四季·今日选股结果（2026年7月3日）
> **报告日期**：2026-07-03（周五）  
> **战法模式**：[此处根据今日市场环境动态写出，例如：防守反击，独立景气方向择优低吸；或 主动进攻，择优配置主线景气等]  
> **总仓位建议**：[此处根据模式动态写出，例如：30%以下，保留35%以上现金；或 50%-70% 仓位等]  

---

## 一、市场环境与模式判定
隔夜美股AI硬件股连续第二天被抛售，情绪宣泄特征明显...（此处写精深的市场大局分析与传导逻辑）

## 二、盘前利空与硬排除清单
| 利空来源 | 具体表现 | 排除板块/个股 |
| :--- | :--- | :--- |
| 美股光通信龙头暴跌 | AAOI -12.99%、LITE -9.09% | A股CPO/光通信：中际旭创、新易盛、天孚通信等 |

---

## 三、核心催化逻辑梳理
### 1. 人形机器人量产在即...
马斯克在社交平台发布弗里蒙特Optimus生产线合影...

---

## 四、今日首选三标（按评分排序）
| 排名 | 代码 | 名称 | 所处方向 | 核心逻辑 | 综合评分 | 流通市值 | 近5日涨幅 |
| :---: | :---: | :---: | :---: | :--- | :---: | :---: | :---: |
| 1 | 688266 | 泽璟制药 | 创新药出海 | 创新药出海授权标杆... | 92 | 180亿 | +15% |

### 详细介入条件与筹码特征
**Top 1: 泽璟制药 (688266)**
- **介入条件**：竞价开盘幅度在-2%至3%之间...
- **K线及筹码特征**：三连阳，量价温和...

---

## 五、重点放弃/排除标的
| 个股名称 | 排除原因 |
|---|---|

---

## 六、后续观察池
| 个股名称 (代码) | 所处方向 | 核心逻辑 | 后续观察点 |
|---|---|---|---|

---

## Ny、今日操作核心总结
1. 总仓位控制在30%以下...
2. 方向第一，优先配置与AI杀跌低相关的独立方向...
"""

        # 4. 组装 User Prompt
        user_prompt = f"""请根据以下最新抓取的盘前数据，生成一份 {date_str[:4]}年{date_str[4:6]}月{date_str[6:]}日 的湖滨四季每日选股决策结果。

【输入数据来源】
---
【日期】：{date_str}
---
{us_stocks_text}
---
{candidates_text}
---
### 知识星球《每日逻辑发掘》语料：
{pdf_text if pdf_text else "暂无今日星球语料"}
---
### 用户Notion自定义输入备注：
{notion_text if notion_text else "今日用户无自定义输入备注"}
---
### 近 3 个交易日首选标的历史决策参考 (防连续推荐拥挤与保持连贯追踪)：
{history_text}
---

【输出格式要求】：
你必须且只能输出一个合法的 JSON 格式字符串，不能包含任何 markdown 标记外的闲扯。
【JSON 防崩溃致命铁律】：
1. 你的所有字符串 Value 内部【绝对禁止】包含真实的换行符（回车键）！如果必须换行，请严格使用转义字符 `\n` 代替。
2. 严禁在 JSON 结构内部使用 Markdown 表格（|---|）或多级标题（##），请统一降级为普通文本或顿号分隔。

JSON 的结构必须如下所示：
{{
  "date": "{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}",
  "market_summary": "这里写‘一、市场环境与模式判定’的正文综述（分析美股走势、亚太情绪传导、战法模式选择等）",
  "bad_news_table": [
    {{
      "source": "利空来源（如美股光通信暴跌）",
      "content": "具体跌幅或内容（如AAOI-12.99%等）",
      "exclude": "排除板块/个股"
    }}
  ],
  "catalyst_list": [
    {{
      "title": "核心催化标题（如：1. 人形机器人）",
      "content": "催化逻辑深度梳理正文"
    }}
  ],
  "top_three_stocks": [
    {{
      "rank": 1,
      "code": "个股代码",
      "name": "个股名称",
      "direction": "所处方向/所属板块（如：人形机器人）",
      "logic": "核心逻辑（详细阐述为什么它是第一/二/三名，包括催化、龙虎榜数据与K线筹码）",
      "score": 92,
      "price_condition": "详细介入条件（例如：竞价0%-3%，量比>2.8，分时承接有力则介入，若低开则等翻红等）",
      "k_features": "K线及筹码特征",
      "market_cap": "流通市值（例如：约 180 亿）",
      "pct_change_5d": "近5日涨幅表现"
    }}
  ],
  "excluded_stocks": [
    {{
      "name": "个股名称",
      "reason": "排除原因（说明由于美股大跌或累计涨幅过大等，今日直接排除）"
    }}
  ],
  "watch_list": [
    {{
      "name": "个股名称 (代码)",
      "direction": "所处方向（如：人形机器人）",
      "logic": "核心逻辑",
      "trigger": "后续观察点"
    }}
  ],
  "operation_summary": "‘七、今日操作核心总结’正文，包括总原则仓位控制等（不要输出重复的表格，只写总结性的核心建议文字，控制仓位在30%以下等提示）",
  "full_markdown_report": "此处生成一份完整的、可以直接复制的 Markdown 报告正文（完全契合 examples 下的报告排版，包含所有的标题、Markdown 表格 and 细节，用于一键保存导出，Markdown 中必须带有当前日期和排版细节）"
}}

请在 full_markdown_report 中以优美的 Markdown 语法排版整篇报告（标题为‘湖滨四季·今日选股结果（X年X月X日）’，各部分表格要美观且对齐，内容必须严谨真实，逻辑要与输入保持绝对的一致）。直接输出该 JSON 字符串即可。"""

        return system_prompt, user_prompt

    @classmethod
    def generate_stock_decision(cls, date_str: str, pdf_text: str, lhb_df: pd.DataFrame, us_stocks: dict, notion_text: str, history_text: str) -> dict:
        """
        核心决策打分引擎：
        - 整合美股情绪排除、A股龙虎榜机构席位、星球PDF逻辑、Notion笔记和近3日历史决策。
        - 组装Prompt输入大模型。
        - 产出结构化JSON结果。
        """
        system_prompt, user_prompt = cls.build_prompts(date_str, pdf_text, lhb_df, us_stocks, notion_text, history_text)
        
        # 5. 调用大模型并解析
        try:
            content = cls._call_llm(system_prompt, user_prompt)
            
            # --- 新增：自动化运行日志持久化 ---
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = os.path.join(Config.LOG_DIR, f"run_log_{date_str}_{timestamp}.md")
            try:
                with open(log_path, "w", encoding="utf-8") as lf:
                    lf.write(f"# 湖滨四季自动化选股系统运行日志\n")
                    lf.write(f"> 日期: {date_str} | 运行时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    lf.write("## 1. ⚙️ System Prompt\n```text\n")
                    lf.write(system_prompt)
                    lf.write("\n```\n\n## 2. 📝 User Prompt\n```text\n")
                    lf.write(user_prompt)
                    lf.write("\n```\n\n## 3. 🤖 大模型原始响应 (Raw Output)\n```json\n")
                    lf.write(content)
                    lf.write("\n```\n")
                print(f"[ENGINE] 本次完整运行日志（含Prompt与Raw Data）已妥善保存至: {log_path}")
            except Exception as log_err:
                print(f"[ENGINE] [警告] 运行日志保存失败: {log_err}")
            # -----------------------------------

            result = json.loads(content)
            print("[ENGINE] 选股决策大模型分析成功。")
            return result
        except json.JSONDecodeError as je:
            print(f"[ENGINE] [警告] 大模型返回的不是合法的 JSON 字符串: {je}，正在尝试自动执行智能自愈清洗...")
            try:
                repaired_content = cls._repair_json_string(content)
                result = json.loads(repaired_content)
                print("[ENGINE] [自愈成功] 成功完成未转义双引号自动修复，数据已顺利解析并装载！")
                return result
            except Exception as repair_err:
                print(f"[ENGINE] [自愈失败] 无法完成 JSON 语法自动纠正: {repair_err}")
                debug_path = os.path.join(Config.OUTPUT_DIR, f"debug_raw_{date_str}.txt")
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"[ENGINE] 原始数据已写入调试文件: {debug_path}")
                raise je
        except Exception as e:
            print(f"[ENGINE] 大模型处理失败: {e}")
            raise e
