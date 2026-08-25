const express = require('express');
const sqlite3 = require('sqlite3').verbose();
const path = require('path');
const fs = require('fs');
const os = require('os');

const app = express();
const PORT = process.env.PORT || 3000;

// --- 路径一致性铁律 ---
// 指向共享数据库 warehouse.db 的绝对路径，保持与 Python 端一致
const DB_PATH = path.resolve(__dirname, '../warehouse.db');

// 静态文件托管
app.use(express.static(path.join(__dirname, 'public')));
app.use(express.json());

// 获取已存储决策的日期列表
app.get('/api/decisions', (req, res) => {
  if (!fs.existsSync(DB_PATH)) {
    return res.json({ success: true, data: [] });
  }

  const db = new sqlite3.Database(DB_PATH, sqlite3.OPEN_READONLY, (err) => {
    if (err) {
      console.error("[DB ERROR]", err.message);
      return res.status(500).json({ success: false, error: err.message });
    }
  });

  db.all("SELECT date FROM daily_decisions ORDER BY date DESC", [], (err, rows) => {
    db.close();
    if (err) {
      return res.status(500).json({ success: false, error: err.message });
    }
    const dates = rows.map(r => r.date);
    res.json({ success: true, data: dates });
  });
});

// 根据具体日期获取详细决策结果
app.get('/api/decisions/:date', (req, res) => {
  const targetDate = req.params.date; // 格式 YYYY-MM-DD
  
  if (!fs.existsSync(DB_PATH)) {
    return res.status(404).json({ success: false, error: "数据库尚未初始化" });
  }

  const db = new sqlite3.Database(DB_PATH, sqlite3.OPEN_READONLY, (err) => {
    if (err) {
      return res.status(500).json({ success: false, error: err.message });
    }
  });

  db.get("SELECT * FROM daily_decisions WHERE date = ?", [targetDate], (err, row) => {
    db.close();
    if (err) {
      return res.status(500).json({ success: false, error: err.message });
    }
    if (!row) {
      return res.status(404).json({ success: false, error: `未找到 ${targetDate} 的选股决策数据` });
    }

    // 将结构化 JSON 字符串解析为 JSON 对象返回
    try {
      res.json({
        success: true,
        data: {
          date: row.date,
          market_summary: row.market_summary,
          top_three_stocks: JSON.parse(row.top_three_json),
          excluded_stocks: JSON.parse(row.excluded_json),
          watch_list: JSON.parse(row.watch_json),
          operation_summary: row.operation_summary,
          full_markdown: row.full_markdown,
          created_at: row.created_at
        }
      });
    } catch (parseErr) {
      res.status(500).json({ success: false, error: "数据库中 JSON 解析失败: " + parseErr.message });
    }
  });
});

// 获取所有历史推荐标的跟踪复盘数据
app.get('/api/trackings', (req, res) => {
  if (!fs.existsSync(DB_PATH)) {
    return res.json({ success: true, data: [] });
  }

  const db = new sqlite3.Database(DB_PATH, sqlite3.OPEN_READONLY, (err) => {
    if (err) {
      console.error("[DB ERROR]", err.message);
      return res.status(500).json({ success: false, error: err.message });
    }
  });

  const limit = parseInt(req.query.limit) || 200;
  db.all("SELECT * FROM stock_trackings ORDER BY decision_date DESC, rank ASC LIMIT ?", [limit], (err, rows) => {
    db.close();
    if (err) {
      // 若表尚未创建，优雅返回空数组
      return res.json({ success: true, data: [] });
    }
    res.json({ success: true, data: rows });
  });
});

// 获取历史跟踪胜率与统计指标
app.get('/api/trackings/stats', (req, res) => {
  if (!fs.existsSync(DB_PATH)) {
    return res.json({ success: true, data: {} });
  }

  const db = new sqlite3.Database(DB_PATH, sqlite3.OPEN_READONLY, (err) => {
    if (err) {
      return res.status(500).json({ success: false, error: err.message });
    }
  });

  db.all("SELECT win_loss_status, max_gain_5d, max_loss_5d, t0_return, t1_return, t3_return, t5_return, rank, direction FROM stock_trackings", [], (err, rows) => {
    db.close();
    if (err || !rows || rows.length === 0) {
      return res.json({ success: true, data: { total: 0, win_rate: 0, avg_max_gain: 0, avg_max_loss: 0 } });
    }

    const total = rows.length;
    const validRecords = rows.filter(r => ['WIN', 'LOSS', 'DRAW'].includes(r.win_loss_status));
    const winCount = rows.filter(r => r.win_loss_status === 'WIN').length;
    const lossCount = rows.filter(r => r.win_loss_status === 'LOSS').length;
    const drawCount = rows.filter(r => r.win_loss_status === 'DRAW').length;
    const pendingCount = rows.filter(r => r.win_loss_status === 'PENDING').length;
    const winRate = validRecords.length > 0 ? Number((winCount / validRecords.length * 100).toFixed(1)) : 0;

    const gains = rows.map(r => r.max_gain_5d).filter(g => g !== null && g !== undefined);
    const losses = rows.map(r => r.max_loss_5d).filter(l => l !== null && l !== undefined);

    const avgMaxGain = gains.length > 0 ? Number((gains.reduce((a, b) => a + b, 0) / gains.length).toFixed(2)) : 0;
    const avgMaxLoss = losses.length > 0 ? Number((losses.reduce((a, b) => a + b, 0) / losses.length).toFixed(2)) : 0;

    const rankStats = {};
    [1, 2, 3].forEach(rankNum => {
      const rRecords = validRecords.filter(r => r.rank === rankNum);
      const rWins = rRecords.filter(r => r.win_loss_status === 'WIN').length;
      rankStats[`Top_${rankNum}`] = {
        total: rRecords.length,
        wins: rWins,
        win_rate: rRecords.length > 0 ? Number((rWins / rRecords.length * 100).toFixed(1)) : 0
      };
    });

    res.json({
      success: true,
      data: {
        total,
        valid_total: validRecords.length,
        win_count: winCount,
        loss_count: lossCount,
        draw_count: drawCount,
        pending_count: pendingCount,
        win_rate: winRate,
        avg_max_gain: avgMaxGain,
        avg_max_loss: avgMaxLoss,
        rank_stats: rankStats
      }
    });
  });
});

function getLocalIp() {
  const interfaces = os.networkInterfaces();
  for (const name of Object.keys(interfaces)) {
    for (const iface of interfaces[name]) {
      if (iface.family === 'IPv4' && !iface.internal) {
        return iface.address;
      }
    }
  }
  return 'localhost';
}

const HOST = '0.0.0.0';
app.listen(PORT, HOST, () => {
  const localIp = getLocalIp();
  console.log(`\n==================================================`);
  console.log(`🚀 湖滨四季 Web 看板服务器已启动！`);
  console.log(`💻 本机访问地址: http://localhost:${PORT}`);
  console.log(`📱 局域网访问地址: http://${localIp}:${PORT} (手机/平板/同WiFi其他电脑可访问)`);
  console.log(`📂 共享数据库路径: ${DB_PATH}`);
  console.log(`==================================================\n`);
});
