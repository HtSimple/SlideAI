# SlideAI 首期设计说明

## 目标

交付一个本地部署的单用户 Web 工作台，让内容创作者录入演示文稿需求、上传参考资料、审核结构化需求与大纲、生成并评估逐页文稿，通过反馈或聊天定向修改，最终导出 Markdown。首期结果是结构化文字，不是 PPTX 或视觉排版成品。

首期验收覆盖《需求分析》的 AC-01 至 AC-20，并满足《开发指导》的最终验收定义。

## 范围与边界

- 包含任务与模型配置、PDF/DOCX/Markdown/TXT 文件处理、任务级 RAG、需求解析、大纲规划、人审中断、逐页生成、质量评估与有限自动修订、聊天修改、Markdown 导出、恢复和本地部署。
- 不包含 PPTX 生成或编辑、幻灯片画布/模板、互联网搜索、多租户、计费和复杂权限。
- 首期只面向本地或受信网络的单用户部署；不宣称可直接安全暴露公网。

## 架构与接口

- 模块化单体 FastAPI API 与独立 Celery Worker。PostgreSQL 保存业务记录和 LangGraph checkpoint；Redis 用于 Celery broker/result backend、任务锁和短期协调；Chroma 保存向量；文件存储使用本地共享卷。
- 后端按 domain、application、infrastructure、workflow、api 分层；前端为 Vue 3 + TypeScript + Vite，Pinia 只存 UI/草稿状态，TanStack Vue Query 管服务端状态。
- REST 使用 `/api/v1`、snake_case、统一错误结构和稳定错误码。所有子资源显式受 `task_id` 约束；写入大纲/内容变更使用 `expected_version`，版本冲突返回 409 `VERSION_CONFLICT`。
- API 覆盖模型目录、任务列表/创建/读取/草稿更新/删除、文件管理、启动/重试/取消、需求、大纲、页面、反馈、评估、模型调用、聊天、变更确认、撤销及 Markdown 预览/下载。补充前端设计要求的 `GET /tasks`；任务列表分页，默认每页 20 条、上限 100 条。
- 所有 LLM 结构化输出先用 Pydantic 校验；失败时仅做一次格式修复，仍失败则返回稳定错误并保留可恢复状态，不把原文写入正式状态。
- `ModelGateway` 统一复杂度档位、节点最低档、超时、最多 2 次可恢复重试、备用链与调用审计。生成模型和 Embedding 独立使用可配置的 OpenAI-compatible endpoint/model/key。Fake provider 用于 CI；真实模型 smoke 可选。
- LangGraph 以 task UUID 为 thread_id，使用 PostgreSQL checkpointer 和 interrupt/Command 恢复。文件解析、向量写入和业务写入之间以补偿任务处理非事务副作用。

## 数据与业务规则

- GenerationTask 是聚合根；业务表包含任务、文件、片段、修订、评估、聊天/消息、模型调用、变更请求和 outbox。文件以随机 UUID 保存；不得以原文件名构造存储路径。
- 任务、文件、片段、对话、页面与模型调用查询均带 task_id。Chroma 单集合 `slideai_chunks`，检索必须带等值 task_id 元数据过滤。
- 任务/大纲/内容使用整数版本；一次任务同一时刻只允许一个工作流。Celery 投递使用 transactional outbox 和幂等键。
- 文件只接受 PDF、DOCX、Markdown、TXT；20 MiB/文件、10 个/任务、提取文本 2,000,000 字符/文件。扫描版 PDF 不做 OCR，报告 `NO_EXTRACTABLE_TEXT`。
- 文本分块默认 800 token、重叠 120；按标题/段落/句号切分，每页检索 top 6；引用只允许来自当前检索结果。
- 大纲页数之和等于目标页数；页数范围 3–50；生成页面页码连续、每页 2–6 条要点。硬规则先于模型评分。
- 评估四项各占 25%，默认 85 分通过，且无阻塞硬规则失败；自动修订最多 2 次，修订范围外页面结构保持不变。
- 影响超过 30% 页面、跨章节或改变关键结构/页数的聊天变更需用户确认；含 expected_task_version；仅可撤销最近一次未被后续修改覆盖的用户/聊天修订。
- 任务与关联数据在用户显式删除前保留。运行中的任务拒绝删除并返回冲突；用户先取消/等待结束。之后清理文件、向量、业务数据与可清理 checkpoint，并记录可重试补偿。

## 前端体验

固定六个页面：任务中心 `/tasks`；新建/编辑 `/tasks/new`、`/tasks/:taskId/edit`；需求确认；大纲编辑；生成进度；文字结果。根路由重定向 `/tasks`。任务状态通过唯一 `resolveTaskRoute(task)` 映射恢复页面。

按文档先实现设计令牌和通用组件，再按任务中心、编辑任务、需求确认、大纲编辑、生成进度、结果页顺序实现。使用浅天蓝与白色，不创建 PPT 缩略图/画布/模板。前台轮询 2 秒、后台 10 秒，进入终结或等待用户状态后停止；不显示虚假总进度。Markdown 使用 markdown-it 渲染并经 DOMPurify 净化。

## 部署、安全与运维

- Python 3.12、uv；FastAPI/Pydantic v2、SQLAlchemy async/Alembic、LangGraph 1.x、LangChain 1.x、Celery 5.x；PostgreSQL 16+、Redis、Chroma server。
- Vue 3、TypeScript strict、Vite、Pinia、TanStack Vue Query、Element Plus、Axios、Vitest、Vue Test Utils、Playwright。
- Docker Compose 服务为 frontend、api、worker、postgres、redis、chroma。CORS 只允许配置的前端源。
- 环境变量覆盖本地 `.env`；密钥不入库、不进 API 响应和日志。JSON 日志包含 request/task/run/node IDs、耗时及稳定错误码，不包含完整 prompt、用户文档或密钥。
- 每阶段质量门槛使用文档列出的 Ruff、Pyright、pytest、ESLint、vue-tsc、Vitest、build；端到端用 Playwright。真实模型 smoke 不作为 CI 必需。
- 项目文档统一保存在 `docs/`；`docs/README.md` 提供启动、配置、迁移、测试、备份、已知限制和文档入口。

## 阶段交付门槛

0. 工程骨架：服务健康、OpenAPI、前端健康调用、空库迁移、质量命令通过。
1. 任务/模型：CRUD、复杂度路由、Fake provider 成功/失败/重试/降级与调用记录。
2. 文件/RAG：四类格式、定位、任务隔离、引用、失败重试和清理补偿。
3. 需求/大纲：校验、确认/澄清、checkpointer 恢复和前端审核页面。
4. 写作/Markdown：分批生成、进度、准确页数、稳定 Markdown 和下载。
5. 质量闭环：硬检查、评分、至多 2 次修订、达到上限后用户接管。
6. 聊天修改：澄清、影响确认、局部变更、版本冲突、撤销及 AC-11 至 AC-14。
7. 加固交付：取消/恢复、幂等/outbox、跨任务隔离、完整 E2E、安全核对、备份恢复和 AC-01 至 AC-20 证据。
