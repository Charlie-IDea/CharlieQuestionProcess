# 知序 · 一对一教学与学情题库

一个以教师私有工作空间为边界的 Vue 3 + Django 应用。支持电脑与手机浏览器，围绕纸笔教学组织：

**资料上传 → 识别切题 → 参考答案审核 → 批改 → 错题归档 → 针对练习 → 复测。**

这是可运行的首版业务实现。真实手写识别、数学解答质量以及生产部署仍需使用实际资料和服务进行验收，不能将演示数据视为AI识别结果。

## 快速运行（Windows / 当前工作区）

需要 Python 3.10+、Node 20.19+ 和 pnpm 11。当前工作区已经建立 `.venv`、安装依赖并初始化本地数据库。

```powershell
# 第一次在新电脑运行
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt
Copy-Item .env.example .env
cd frontend
pnpm install
cd ..

# 运行本地应用（同时启动前后端；Ctrl+C 停止）
./scripts/start-dev.ps1 -Demo
```

打开 [本地工作台](http://127.0.0.1:5173/)。演示账号：`demo@zhixu.local`，密码：`ZhixuDemo!2026`。

演示命令仅在 `DEBUG=1` 可用，不覆盖已有数据；学生和作答均为合成示例。可用 `seed_demo --email ... --password ...` 指定其他本地演示账户。生产环境不运行演示命令。

也可分别运行：

```powershell
.venv/Scripts/python backend/manage.py migrate
.venv/Scripts/python backend/manage.py seed_demo
.venv/Scripts/python backend/manage.py runserver 127.0.0.1:8000
# 另开终端
cd frontend
pnpm run dev
```

本地 SQLite 存于 `backend/db.sqlite3`，原件存于 `backend/private_media`，二者均被Git忽略。Vite代理 `/api` 到后端；浏览器使用会话Cookie与CSRF校验。

## 实际功能

| 模块 | 已实现行为 |
| --- | --- |
| 账户 | 邮箱注册/验证/重发、登录退出、重置密码、修改密码、独立工作空间 |
| 学生档案 | 基础资料、目标、备注、归档、学习计划、测试时间线、知识点作答统计 |
| 资料录入 | PDF/JPG/PNG批量上传，题目页/答案页/学生作答页分别标记，后台进度、重试与异常状态 |
| 外部试卷 | 空白卷、附答案卷、已作答卷；按题号重建结构，跨页合并提示，答案页匹配，缺答案时生成待审AI解答 |
| 审核与题库 | 题干/选项/知识点/分值修正、原图裁切调整、配图区域、合并拆分、文字查重、题库答案关联、独立答案版本、修订副本 |
| 组卷 | 手动选题、按题型/知识点/难度/题量生成候选卷，发布时固定题目和答案快照 |
| 打印 | KaTeX公式与配图的打印视图，浏览器打印保存PDF；带签名二维码与定位点的学生专属答题卡PDF |
| 答题卡 | OpenCV定位透视校正、ZXing解码、学生/试卷/模板校验、四至八选项涂点检测、缺页/重复页拦截 |
| 批改 | 选择题集合比较、支持范围内的数值/分数比较；AI解答题评分建议；教师确认识别、定分和改分历史 |
| 错题复练 | 失分题自动归档，改分同步更新；原题重做、同知识点同题型相近难度选题；复练关联原作答，保留历史 |
| 文件与审计 | 所有文件/裁切图片须登录并经过工作空间权限校验；关键审核、发布、归档和评分操作记录 |

### 推荐体验顺序

1. 登录后查看演示学生、测试、错题和学习计划。
2. 在“资料录入”新建外部卷批次。收集题库选“题库资料”；学生卷选“学生作业/测试”并绑定学生。
3. 每个文件指定内容角色；纸卷题目与单独答案页可以放在同一批次。不同学生分批上传。
4. 启动识别，核对题干、题号、配图、分值及参考答案。有答案版本冲突时明确选择正确版本。没有可靠解答时保留待审核，不强行批改。
5. 确认入库并归档。学生卷会建立逐题作答记录；进入批改工作台确认识别后定分。
6. 在错题页面为同一学生选题，生成原题或同类题练习。从练习卷建立新的作答记录，保留与首次失分的关联。

## 配置OCR与AI

未配置AI时，系统保留原件并显示“待配置/待处理”，不会返回虚构OCR或分数。演示账户中的审核样例由命令编写，页面会明确标识。

在 `.env` 设置：

```dotenv
AI_BASE_URL=https://your-provider.example/v1
AI_API_KEY=your-server-side-key
AI_MODEL=your-vision-model
OCR_PROVIDER=vision
AUTO_GRADING_ENABLED=0
```

服务需支持 `POST /chat/completions`、图片内容和JSON对象输出。具体协议见 [Chat Completions 官方参考](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。供应商支持的参数可能不同，接入后须实际验证。密钥仅保存在服务器环境中，不发到浏览器。

默认用视觉服务提取题目；无随卷参考答案时另发独立解题请求，结果保存为待审核答案。AI解答题评分需要教师触发且始终只是建议。默认数值自动比较只支持十进制常数和简单分数，带变量、定义域、单位、根式及证明不自动判定。

PaddleOCR为可选工作进程依赖：

```powershell
.venv/Scripts/python -m pip install -r backend/requirements-ocr.txt
# 设置 OCR_PROVIDER=paddle 后重启worker
```

该模式用 PP-StructureV3 提供文字和版面辅助，再由视觉服务重建试题结构。模型首次使用需要下载；CPU/GPU环境与模型权重需单独准备。本机未安装或实测这套大模型依赖。

答题卡默认复用OpenCV与ZXing，使用项目共享模板执行涂点识别。可将 `OMR_CHECKER_DIR` 指向已安装依赖的 [OMRChecker](https://github.com/Udayraj123/OMRChecker) 本地仓库，启用四选项CLI交叉检查。识别不一致转人工；此可选适配器尚未在本机运行上游仓库验收。

`MAX_BATCH_PAGES` 默认100，`MAX_AI_CALLS_PER_BATCH` 默认110。调用失败也计入调用次数以约束重试费用；记录供应商返回的token用量，不推算未经确认的金额。

初次整页识别会将上传页面发送到配置的视觉服务；后续解题、评分优先发送题目区域。请在上传前遮盖不需要的姓名、联系方式等信息，并确认所选服务可用于你的教学资料。

## 邮件与账号

开发环境默认邮件打印到后端终端，复制其中的链接完成验证或重置。真实对外注册必须配置SMTP：

```dotenv
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_USE_TLS=1
EMAIL_HOST_USER=your-account
EMAIL_HOST_PASSWORD=your-secret
DEFAULT_FROM_EMAIL=teacher@example.com
APP_URL=https://your-domain.example
```

验证链接24小时有效；密码重置链接使用Django单次有效token。修改密码会使其他设备的旧会话失效。

## 云端部署

提供 Docker Compose：PostgreSQL、RabbitMQ、迁移任务、Django API、Celery worker、超时巡检beat及Nginx前端。当前机器没有Docker命令，配置尚未进行容器实跑。

1. 复制 `.env.example` 为 `.env`，设置独立随机的 `SECRET_KEY`、`POSTGRES_PASSWORD`、`RABBITMQ_PASSWORD`，配置AI和邮件。
2. 本地容器试跑：`docker compose up --build -d`，打开 `http://127.0.0.1:8080`；设置 `APP_URL=http://127.0.0.1:8080`，`CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8080`。
3. 公网部署设置 `DEBUG=0`，`DOMAIN=你的域名`，`ALLOWED_HOSTS=你的域名`，`APP_URL=https://你的域名`，`CSRF_TRUSTED_ORIGINS=https://你的域名`。域名解析到服务器，开放80/443，再运行 `docker compose --profile production up --build -d`。Caddy申请TLS证书；数据库、队列与API不直接暴露公网。
4. 查看服务：`docker compose logs -f api worker`。需要管理后台时运行 `docker compose exec api python manage.py createsuperuser`；后台仅供平台管理员维护。

部署使用异步worker；本地开发默认 `TASKS_EAGER=1` 同步执行，便于一页小样本调试。不支持以Windows Celery进程作为生产worker；生产使用Linux容器。

原件默认保存在私有命名卷。配置私有S3：`S3_BUCKET`、`S3_ENDPOINT_URL`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_REGION`；访问仍通过鉴权API，不暴露公共对象URL。替换存储需迁移既有文件，不能只改配置后丢弃本地卷。

## 测试、备份和验收

```powershell
.venv/Scripts/python backend/manage.py test core.tests
.venv/Scripts/python backend/manage.py check
cd frontend
pnpm run build
```

详见 [真实资料验收说明](docs/VALIDATION.md) 和 [架构与接口](docs/ARCHITECTURE.md)。评测工具已提供，200页真实人工标注集需要后续收集，当前未获得实际资料或AI密钥，未测真实识别准确率、调用成本及周处理量。

本地SQLite：运行 `./scripts/backup.ps1`，再备份 `backend/private_media`。恢复时停止服务，将数据库备份复制为 `backend/db.sqlite3`，恢复匹配的原件目录并执行迁移。正式恢复前先在独立目录试跑。

PostgreSQL：`docker compose exec -T db pg_dump -U teaching -Fc teaching` 输出到二进制备份文件；恢复到独立测试库执行 `pg_restore` 验证。同步备份私有文件卷或启用S3版本与独立备份。不要将数据库、原件、`.env`或密钥提交Git。

## 当前边界

- 外部试卷结构由模型建议、教师确认，不承诺任意复杂版面一次正确；缺图、遮挡、跨页和同题号需复核。
- 相似题先采用本空间文字相似度和知识点规则；图像/公式嵌入与pgvector属于后续增强。
- PDF试卷导出通过浏览器打印，答题卡为服务器生成PDF；尚未提供独立后台的整卷PDF渲染服务。
- 手机响应式网页已实现；原生App、小程序、离线同步、学生/家长登录、公共题库和AI变式题不在本版。
- 生产负载、私有S3、PaddleOCR、上游OMRChecker和真实AI服务需在目标环境中继续验证。

## 开源复用

核心依赖使用 Django、Django REST Framework、Vue、Celery、PaddleOCR（可选）、OpenCV、ZXing、SymPy、KaTeX、ReportLab及pypdfium2；原项目许可证与通知须随依赖保留。本仓库未复制学之思或其他AGPL考试系统代码。
