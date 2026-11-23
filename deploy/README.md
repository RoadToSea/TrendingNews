# TrendRadar Web 生产部署说明（香港服务器 `budahk`）

所有模板均以域名子路径 `/radar/` 为准，禁止将任何真实密钥或 Token 写入仓库。

## 1. 服务器前置准备

1. **增加 2GB Swap 缓冲**（保护 3.7 GiB 内存环境在并发调用 `agy` 或依赖安装时不触发 OOM）：
   ```bash
   sudo fallocate -l 2G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```
2. **安装 Python 3.12 与系统工具**：
   ```bash
   uv python install 3.12
   sudo apt-get update && sudo apt-get install -y sqlite3
   mkdir -p /home/liu/trendradar/backend /home/liu/trendradar/frontend-dist \
            /home/liu/trendradar-data/agy-sandbox /home/liu/trendradar-backups
   ```

## 2. 本地构建前端并同步代码

在本地 Windows 工作站执行：

```powershell
cd D:\Vscode\code\TrendRadar\frontend
$env:VITE_BASE_PATH='/radar/'; pnpm run build
```

将以下目录同步至服务器 `/home/liu/trendradar/`：
- `backend/` -> `/home/liu/trendradar/backend/`
- `trendradar/` -> `/home/liu/trendradar/trendradar/`
- `config/`（仅初始种子需要）-> `/home/liu/trendradar/config/`
- `frontend/dist/` -> `/home/liu/trendradar/frontend-dist/`

## 3. 配置后端环境与 systemd 服务

1. 在服务器同步后端依赖：
   ```bash
   cd /home/liu/trendradar/backend
   uv sync --frozen
   ```
2. 写入环境文件（使用强随机 `TRENDRADAR_SECRET_KEY` 与初始管理员密码）：
   ```bash
   sudo mkdir -p /etc/trendradar
   sudo cp deploy/backend.env.example /etc/trendradar/backend.env
   sudo chmod 600 /etc/trendradar/backend.env
   sudo nano /etc/trendradar/backend.env
   ```
3. 注册并启动 systemd 常驻服务：
   ```bash
   sudo cp deploy/trendradar-web.service /etc/systemd/system/trendradar-web.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now trendradar-web
   sudo systemctl status trendradar-web
   ```

## 4. 配置 Nginx 子路径反代

1. 将 `deploy/nginx-radar.conf` 内容放入 `/etc/nginx/sites-available/freeroadtosea.site.conf` 对应绑定业务域名的 `server { ... }` 块中（保持默认 `server_name _;` 返回 `404`）。
2. 检查语法并热加载：
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

## 5. 配置每日 SQLite 热备份（cron）

```bash
chmod +x /home/liu/trendradar/deploy/backup-sqlite.sh
crontab -e
# 每日凌晨 03:30 热备份（保留最近 14 天）
30 3 * * * TRENDRADAR_DB_PATH=/home/liu/trendradar-data/trendradar.db /home/liu/trendradar/deploy/backup-sqlite.sh >> /home/liu/trendradar-backups/backup.log 2>&1
```
