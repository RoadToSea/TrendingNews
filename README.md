# TrendRadar Web

多平台热点聚合、跨天趋势图谱、AI 研判与报告归档系统（基于 FastAPI + SQLite WAL + React/Tailwind/shadcn）。

## 核心功能

- **平台热点**：实时聚合多平台榜单、RSS 订阅及海外数据源，支持飙升榜筛选、关键词检索与增量 SSE 数据更新。
- **领域归类**：通过 AI 自动将跨平台报道归纳为标准化热点事件并划分领域，支持按领域筛选与事件关联溯源。
- **趋势图谱**：以今日为横轴中心对称展示近期热点演变，区分跨天连续热点折线与单日离散热点圆点，支持点击节点下钻详情。
- **报告归档与词频分析**：支持按每日总体、指定领域或单个事件生成结构化分析报告，可拖拽调节报告列表与阅读区比例，并实时统计关键词词组命中情况。
- **AI 研判助手**：支持随时从页面点选新闻或事件注入上下文发起多轮流式对话，并将研判过程一键沉淀为报告。
- **邀请码注册与管理后台**：管理员可签发并控制邀请码的有效次数与过期时间，查看注册成员来源并实时启用/停用账号；所有账号均支持自助修改登录密码。
- **自动化配置中心**：集中配置平台与 RSS/海外数据源、简化词组匹配与过滤规则、多协议 AI 模型（OpenAI / Anthropic / Antigravity）、开场提示词及定时调度任务（自动保存并热生效）。

## 目录结构

```text
TrendRadar/
├── backend/                # FastAPI 后端服务、SQLite 仓储层、采集/归类/AI 服务与 pytest 测试
├── frontend/               # React + TypeScript + Vite + Tailwind + shadcn 前端应用
├── trendradar/             # 后端 legacy_bridge 复用的采集、频率词匹配、时间工具与通知推送核心模块
├── config/                 # 首次初始化数据库的种子配置（config.yaml、frequency_words.txt）
└── deploy/                 # 生产环境 Nginx、systemd 与 SQLite 热备份模板
```

## 本地开发

### 1. 启动后端（默认端口 `8000`）

```powershell
cd D:\Vscode\code\TrendRadar\backend
uv sync --frozen
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

首次启动且数据库尚未建立用户时，若未配置 `TRENDRADAR_ADMIN_PASS`，控制台会输出随机生成的初始管理员密码；已注册成员可通过管理员签发的邀请码在 `/radar/register` 完成自助注册。

### 2. 启动与构建前端

开发调试（`vite.config.ts` 已代理 `/radar/api` 到本地后端）：

```powershell
cd D:\Vscode\code\TrendRadar\frontend
pnpm install
pnpm run dev
```

生产构建（产物输出至 `frontend/dist/`）：

```powershell
cd D:\Vscode\code\TrendRadar\frontend
$env:VITE_BASE_PATH='/radar/'
pnpm run build
```

## 质量验证

```powershell
# 后端单元测试与集成测试
cd D:\Vscode\code\TrendRadar\backend
uv run pytest -v

# 前端类型检查
cd D:\Vscode\code\TrendRadar\frontend
pnpm exec tsc --noEmit
```

## 生产部署

### Docker Compose（推荐）

```bash
cp .env.docker.example .env.docker
chmod 600 .env.docker
# 编辑 .env.docker 填入随机 TRENDRADAR_SECRET_KEY
docker compose up -d --build
```

后端服务绑定于 `127.0.0.1:8000`，前端静态容器绑定于 `127.0.0.1:8085`，由宿主机 Nginx 统一按 `/radar/` 子路径反代；详见 [deploy/README.md](deploy/README.md)。
