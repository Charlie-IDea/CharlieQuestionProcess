# 架构与接口

## 数据边界

`Workspace.owner` 与Django用户一对一，所有业务对象继承 `Owned`。API查询必须首先按当前工作空间过滤，所有可写关联外键通过序列化器限制到同一工作空间。前端传入的对象ID不产生访问权。

原件存储名为工作空间UUID与随机UUID，不使用用户原始路径。文件、原始页及裁切图均通过鉴权接口读取，`Cache-Control: private, no-store`；没有公开media路由。

## 关键关系

```text
Workspace → Student → LearningPlan
Workspace → ImportBatch → SourceFile → SourcePage
ImportBatch → Question → AnswerRevision
Paper → PaperItem(question + immutable snapshot)
Student + Paper + test_date → Submission → Attempt → GradeRevision
Attempt → Mistake
Practice PaperItem.origin_response → original Attempt
```

Question保留整题原图区域、独立印刷配图区域、题目文字与学生作答提取结果。AnswerRevision独立保存随卷答案、AI解答、教师填写与题库关联版本。批准某个答案版本时撤销该题其他已批准版本；历史PaperItem快照不变。

Paper发布后禁止改题，PaperItem保留答案版本ID、公式文字、配图和评分细则。外部卷关联已有Paper时按唯一题号映射，并核对题干及参考答案，阻止不同版本错配。OCR文字差异需要教师修正后确认，不自动猜测。

Attempt保存识别结果、教师确认状态、建议分与最终分。确认最终评分的事务同时写GradeRevision和Mistake；改分保留历史。原题复练使用原快照，另建Submission和Attempt，并关联原始Attempt。

## 状态与任务

批次：`uploaded → queued → processing → review → committed`。缺配置为 `blocked`，处理失败为 `failed`。没有原件丢失或自动打零分的回退。

每次排队增加generation。任务只有在generation匹配且批次queued时取得处理权，重复投递不会重复建题。全部页面提取成功后才批量建立审核题目，自动解题保存待审版本。无答案或识别冲突不会直接进入正式评分。

AI临时故障最多重试两次；每次调用受批次预算上限控制。Celery硬时限600秒。beat每5分钟检查20分钟未完成的排队/处理批次：没有题目时允许重试；已有题目时恢复审核，保留人工工作。生产需启动beat。

本地SQLite用于单机开发；并发任务和事务锁的生产验收使用PostgreSQL。当前未进行真实吞吐测试。

## API清单

请求使用同源会话Cookie，写请求携带 `X-CSRFToken`。先 `GET /api/session/` 获取用户与CSRF token，登录后使用返回的新token。错误为 `{"detail":...}`；当前列表返回数组，首期未做服务端分页。

| API | 用途 |
| --- | --- |
| GET session/ | 当前用户与CSRF |
| POST auth/register/, verify/, resend/ | 注册、验证、重发邮件 |
| POST auth/login/, logout/, forgot/, reset/, password/ | 会话与密码管理 |
| GET dashboard/ | 当前空间指标、近期导入、待办和服务用量 |
| GET/POST students/；GET/PATCH students/{id}/ | 学生档案 |
| GET students/{id}/report/ | 时间线、错题、知识点和计划 |
| GET/POST plans/；PATCH plans/{id}/ | 学习计划 |
| GET/POST questions/；GET/PATCH questions/{id}/ | 题库及修正 |
| POST questions/{id}/answer/ | 创建不可覆盖的待审答案版本 |
| POST questions/{id}/solve/ | AI独立解题，保存待审核答案 |
| POST questions/{id}/approve/ | 确认选定answer_id及识别问题 |
| POST questions/bulk-approve/ | 事务性批量确认，最多100题 |
| GET questions/{id}/duplicates/；POST questions/{id}/link/ | 本空间查重与明确关联答案 |
| POST questions/merge/；questions/{id}/split/ | 合并、拆分待审题块 |
| POST questions/{id}/clone/ | 保留原题，另建修订副本 |
| POST batches/upload/ | multipart上传：files、逐文件roles及批次资料 |
| GET batches/；GET batches/{id}/ | 批次、文件、原始页及审核题目 |
| POST batches/{id}/process/ | 入队处理或重试 |
| POST batches/{id}/commit/ | 审核后幂等归档 |
| GET files/{id}/download/；pages/{id}/image/ | 私有文件/图片，image可带bbox归一化裁切参数 |
| GET/POST papers/；GET/PATCH papers/{id}/ | 试卷草稿与已发布记录 |
| POST papers/generate/ | 按知识点、题型、难度与题量生成草稿 |
| POST papers/{id}/items/；remove-item/；publish/ | 选题、移除、冻结版本 |
| GET papers/{id}/card/?student={id} | 签名二维码专属答题卡PDF |
| GET/POST submissions/；GET submissions/{id}/ | 建立或读取作答记录 |
| POST attempts/{id}/recognize/ | 教师确认/修正学生作答 |
| POST attempts/{id}/suggest/ | 规则比较或AI评分建议 |
| POST attempts/{id}/grade/ | 最终定分，revision防止旧页面覆盖新评分 |
| GET mistakes/；PATCH mistakes/{id}/ | 错题、教师确认掌握、备注与复练证据 |
| POST mistakes/practice/ | 同一学生的原题/同类题练习，保留来源关联 |
| GET audit/ | 当前空间的关键业务操作 |

## 引擎适配

- `ai.py`：服务端Chat Completions兼容请求、JSON校验、图片编码、用量统计；客户端无密钥。
- `ocr.py`：可选PP-StructureV3辅助识别，独立安装模型运行环境。
- `omr.py`：模板v1共享几何坐标，签名二维码绑定学生/试卷/页码；图像定位、旋转、涂点检测。
- `omrchecker.py`：可选上游CLI适配，只执行运维配置的本地仓库；使用私有临时目录、不接收网络命令。
- `services.py`：审核、发布快照、归档、保守答案比较、最终评分与错题状态事务。

批量识别与自动解题在worker执行；教师主动触发的单题AI解题、评分建议目前在API请求内执行，150秒超时，Nginx/Gunicorn配套180秒。后续高并发时可将单题操作也迁移为异步任务。
