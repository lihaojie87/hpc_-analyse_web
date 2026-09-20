# WorkBuddy 跨电脑接续必读

## 项目定位
HPC 性能画像数据管理平台：React/Vite/TypeScript 前端 + FastAPI 后端 + Alembic + PostgreSQL/SQLite + Redis + Outbox/SSE + 飞书同步。

## 当前权威源码
- 继续开发目录：`backend/`、`frontend/`、`infra/`
- GitHub 仓库：`git@github.com:lihaojie87/hpc_-analyse_web.git`
- 生产环境：另有部署副本，不在本仓库中保存生产 `.env`、数据库、备份、令牌或日志。

## 当前进度
- T01~T04：核心认证、RBAC、记录 CRUD、模板、飞书 Sheets 导入管线已有实现和测试。
- 模板发布约束已完成：记录只能绑定 `published` 模板版本；未发布版本返回 409。
- T05 Outbox/SSE/Redis：代码与生产补救基础设施已存在，但生产 authenticated SSE 端到端事件送达尚未最终签收。
- T05.4：本地备份成功回调、SHA256 防篡改和 review-only systemd 模板已完成；生产 daemon、Webhook、变更窗口、凭据轮换和 CentOS 动态证据未闭环。
- 飞书用户链接是 Base/bitable：`/base/E8bpbNtGJaEzFlsfe4xcNEbanHd`，不是 Sheets。
- Base 适配器与只读预览层已完成并独立复验：Base 读取 13/13，预览 14/14，相关回归 36/36。
- 正式 Base 导入尚未完成：尚未接入 `import_service`，尚未实现 `credential_ref` 解析、字段映射持久化和首灌目录策略。

## 关键证据（不在 GitHub 中）
完整报告位于原 WorkBuddy 工作区的 `outputs/`，本仓库通过忽略规则不提交这些报告。继续工作前，应从对话上下文或本机项目记忆恢复：
- `qa-feishu-import-readiness-20260919.md`
- `qa-db-readonly-20260919.md`
- `impl-feishu-bitable-adapter.md`
- `impl-feishu-bitable-preview.md`
- `qa-verify-feishu-bitable-preview.md`
- `qa-prod-sse-readonly-20260919.md`

## 继续开发的推荐顺序
1. 阅读 `backend/app/adapters/feishu.py` 与 `backend/app/services/feishu_bitable_preview.py`。
2. 为 Base 字段建立字段类型到模板路径的显式 mapping 模型/配置，不要猜字段语义。
3. 在本地隔离 PostgreSQL 上做 preview/dry-run/staging；禁止 publish/promote。
4. 先处理已有 `performance_records` 的版本化同步路径。
5. 再设计首灌：明确稳定键、目录记录字段、模板版本和去重规则后，单独实现并测试。
6. 最后再评估凭证服务接入、生产 PostgreSQL 切换和生产导入窗口。

## 本机环境
### macOS
- Python 3.11+，推荐使用 `python3 -m venv backend/.venv`。
- Node.js 20+，npm 10+。
- PostgreSQL 16+；Redis 7+。
- Docker Desktop 可选；如使用 Docker，读取 `infra/docker-compose.yml` 和 `.env.example`。

### Windows 当前验证环境（仅供参考）
- Python venv：`backend/.venv/`
- Node：WorkBuddy managed Node 22
- 本地原生 PostgreSQL：`127.0.0.1:55432`
- 本地原生 Redis：`127.0.0.1:56379`
- 生产/默认后端实际仍曾使用 SQLite；不要把 Windows 本地端口或 `.local/` 复制到 Mac。

## Mac 初始化
```bash
git clone git@github.com:lihaojie87/hpc_-analyse_web.git
cd hpc_-analyse_web
cp .env.example .env
# 编辑 .env：至少填写唯一 HPC_JWT_SECRET；不要提交 .env
python3 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -U pip
pip install -e backend
cd frontend
npm ci
cd ..
```

## 运行本地 SQLite 开发模式
```bash
source backend/.venv/bin/activate
set -a; source .env; set +a
cd backend
python -m alembic upgrade head
python -m pytest --basetemp=.pytest_tmp_mac -q
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
另开终端：
```bash
cd frontend
npm run dev
```

## 运行本地 PostgreSQL/Redis 模式
不要使用生产地址。使用本机自己的数据库和 Redis，并将端口写入未提交的 `.env`：
```text
HPC_DATABASE_URL=postgresql+asyncpg://<local-user>:<local-password>@127.0.0.1:5432/<local-db>
HPC_REDIS_URL=redis://127.0.0.1:6379/0
```
```bash
source backend/.venv/bin/activate
cd backend
python -m alembic upgrade head
python -m pytest tests/test_t05_2_worker.py tests/test_t05_1_qa_independent.py --basetemp=.pytest_tmp_mac_pg -q
```

## Base 只读预览原则
- Base 读取必须显式提供 `app_token`、`table_id` 和访问令牌。
- 缺 Token 必须 fail-closed。
- 预览只允许 GET，不写 Base。
- 导入演练只允许写 `source_snapshots`、`import_jobs`、`import_row_errors`、`import_diffs`、`data_versions(staging)`、`performance_record_versions`。
- 禁止写 `performance_records`、`catalog_heads`；禁止 `publish/promote`。
- 不要把真实飞书 Token 写入代码、`.env.example`、报告或 GitHub。

## 代码验证
```bash
cd backend
python -m pytest tests/test_t04_feishu_rate_limit.py tests/test_feishu_bitable_preview.py --basetemp=.pytest_tmp_mac_bitable -q
cd ../frontend
npx tsc --noEmit -p tsconfig.json
npm run build
```

## 当前不能宣称完成的事项
- 生产 PostgreSQL 架构切换。
- Base 正式导入端到端。
- 首灌新建目录策略。
- authenticated SSE 真实事件送达。
- T05.4 生产备份告警闭环。
- T05 整体终签。
