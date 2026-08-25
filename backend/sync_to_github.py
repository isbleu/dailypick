import os
import sys
import json
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.config import Config

def sync():
    db_path = Config.DB_PATH
    target_repo_dir = r"d:\Vibe\tmp_pick"
    target_pick_dir = os.path.join(target_repo_dir, "pick")
    target_data_dir = os.path.join(target_pick_dir, "data")
    
    print("==================================================")
    print("[SYNC] 正在启动 GitHub Pages 选股数据云端同步程序...")
    print("==================================================")
    
    if not os.path.exists(target_repo_dir):
        print(f"[错误] 未找到克隆的 GitHub 仓库目录: {target_repo_dir}")
        return
        
    os.makedirs(target_data_dir, exist_ok=True)
    
    # 0. 同步前端静态页面资源 (HTML/CSS/JS)
    import shutil
    frontend_public_dir = os.path.join(Config.PROJECT_ROOT, "frontend", "public")
    for static_file in ["index.html", "index.css", "index.js"]:
        src_path = os.path.join(frontend_public_dir, static_file)
        dst_path = os.path.join(target_pick_dir, static_file)
        if os.path.exists(src_path):
            shutil.copy2(src_path, dst_path)
    print(f"[STATIC] 成功同步前端最新页面资产至 GitHub Pages 目录。")
    
    # 1. 从本地数据库中查询所有的决策数据
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 查询所有字段，按日期降序排列
        cursor.execute("""
            SELECT date, decision_json, market_summary, top_three_json, excluded_json, watch_json, operation_summary, full_markdown 
            FROM daily_decisions ORDER BY date DESC
        """)
        rows = cursor.fetchall()
    except Exception as e:
        print(f"[错误] 读取本地数据库失败: {e}")
        conn.close()
        return
        
    conn.close()
    
    if not rows:
        print("[提示] 数据库中暂无选股决策数据，无需同步。")
        return
        
    date_list = []
    print(f"[DB] 成功检索到 {len(rows)} 天的历史选股决策记录。")
    
    # 2. 为每一天生成静态 YYYY-MM-DD.json 文件
    for row in rows:
        (date_val, decision_json, market_summary, top_three_json, 
         excluded_json, watch_json, operation_summary, full_markdown) = row
         
        if not date_val:
            continue
            
        # 统一转为 "YYYY-MM-DD" 的标准文件名格式
        if len(date_val) == 8:
            formatted_date = f"{date_val[:4]}-{date_val[4:6]}-{date_val[6:]}"
        else:
            formatted_date = date_val
            
        date_list.append(formatted_date)
        
        data_file_path = os.path.join(target_data_dir, f"{formatted_date}.json")
        try:
            # 优先从原始 decision_json 恢复，字段完整无缺
            if decision_json:
                data_dict = json.loads(decision_json)
            else:
                # 针对历史老数据进行平滑降级拼装，确保向前兼容性
                data_dict = {
                    "date": formatted_date,
                    "market_summary": market_summary,
                    "bad_news_table": [],
                    "catalyst_list": [],
                    "top_three_stocks": json.loads(top_three_json) if top_three_json else [],
                    "excluded_stocks": json.loads(excluded_json) if excluded_json else [],
                    "watch_list": json.loads(watch_json) if watch_json else [],
                    "operation_summary": operation_summary,
                    "full_markdown_report": full_markdown
                }
            with open(data_file_path, "w", encoding="utf-8") as f:
                json.dump(data_dict, f, ensure_ascii=False, indent=2)
        except Exception as err:
            print(f"[错误] 写入/解析静态文件失败 {formatted_date}: {err}")
            
    # 3. 生成索引文件 list.json
    list_file_path = os.path.join(target_data_dir, "list.json")
    try:
        with open(list_file_path, "w", encoding="utf-8") as f:
            json.dump(date_list, f, ensure_ascii=False, indent=2)
        print(f"[LIST] 成功生成数据索引文件: {list_file_path}")
    except Exception as err:
        print(f"[错误] 生成数据索引文件失败: {err}")
        return

    # 3.5 导出复盘跟踪与胜率统计数据 (trackings.json & tracking_stats.json)
    try:
        from backend.stock_tracker import StockTracker
        trackings_conn = sqlite3.connect(db_path)
        trackings_conn.row_factory = sqlite3.Row
        t_cursor = trackings_conn.cursor()
        t_cursor.execute("SELECT * FROM stock_trackings ORDER BY decision_date DESC, rank ASC")
        t_rows = [dict(r) for r in t_cursor.fetchall()]
        trackings_conn.close()

        stats_data = StockTracker.get_summary_stats()

        for dest_dir in [target_data_dir, os.path.join(Config.PROJECT_ROOT, "frontend", "public", "data")]:
            if os.path.exists(os.path.dirname(dest_dir)):
                os.makedirs(dest_dir, exist_ok=True)
                with open(os.path.join(dest_dir, "trackings.json"), "w", encoding="utf-8") as f:
                    json.dump(t_rows, f, ensure_ascii=False, indent=2)
                with open(os.path.join(dest_dir, "tracking_stats.json"), "w", encoding="utf-8") as f:
                    json.dump(stats_data, f, ensure_ascii=False, indent=2)
        print(f"[TRACKER] 成功导出复盘跟踪数据 ({len(t_rows)} 条) 与胜率统计。")
    except Exception as trk_err:
        print(f"[TRACKER] 导出复盘跟踪数据异常: {trk_err}")
        
    # 4. 执行 Git 提交并推送至 GitHub Pages 仓库
    print("\n[GIT] 正在执行 Git 同步推送程序...")
    try:
        # git add pick
        subprocess.run(["git", "add", "pick/"], cwd=target_repo_dir, check=True)
        
        # 检查是否有未提交的修改，防止空白 commit 报错
        status_res = subprocess.run(["git", "status", "--porcelain"], cwd=target_repo_dir, capture_output=True, text=True)
        if not status_res.stdout.strip():
            print("[GIT] 静态数据无任何变更，无需提交推送。")
            return
            
        # git commit
        commit_msg = f"Auto sync stock decision data at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=target_repo_dir, check=True)
        
        # 尝试 pull --rebase 防止云端有别的端推送造成的进度落后
        print("[GIT] 正在同步拉取远程更新...")
        subprocess.run(["git", "pull", "--rebase"], cwd=target_repo_dir, check=False)
        
        # git push
        print("[GIT] 正在向 GitHub 推送代码，请稍候...")
        push_res = subprocess.run(["git", "push"], cwd=target_repo_dir, capture_output=True, text=True)
        if push_res.returncode == 0:
            print("==================================================")
            print("[SUCCESS] 选股结果已成功同步至云端看板！")
            print("[URL] 您可以通过此 URL 访问：https://isbleu.github.io/pick")
            print("==================================================")
        else:
            print(f"[GIT] 推送失败! 错误返回:\n{push_res.stderr}")
            print("\n[提示]: 如果推送遭遇权限问题，您可以在终端手动进入 'd:\\Vibe\\tmp_pick' 目录下执行 'git push' 并按照提示进行 GitHub 登录授权即可！")
            
    except Exception as git_err:
        print(f"[GIT] 运行 Git 命令遭遇异常: {git_err}")

if __name__ == "__main__":
    sync()
