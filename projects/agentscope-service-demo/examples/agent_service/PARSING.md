# 文档解析适配

知识库「设置 → 上传与解析默认设置」保存默认值；上传文件可覆盖。
文档详情「处理 / 审核」显示实际解析器、产物，支持重新解析。
新上传强制分步骤：解析 → 等待人工确认 → 生成分片草稿 → 等待人工确认 → 向量化入库。
未点击确认不会生成分片或调用向量模型。重启、刷新、重复队列消息不会越过审核。
审核使用版本校验；向量化只使用已确认的持久化分片草稿，不会悄悄重新切分。
已有已就绪文件保持可检索；主动重新解析后进入人工审核流程。
旧文件不自动重跑。重新解析会重建向量，已有图谱需要手动重建。

## 三条独立路径

- MinerU 本地：对接 **MinerU 4.x 自部署 V1 HTTP API**，不是旧版 `/file_parse`。
- MinerU 云端：对接 `https://mineru.net/api/v4` 精准解析 API。
- 视觉 LLM：使用凭证中启用并配置好的 OpenAI 兼容 LLM，逐页图像转 Markdown。必须确认该模型实际支持视觉。不是所有 LLM 都支持图片。

本地服务不可用时直接报错，绝不自动向云端上传。Markdown/TXT（UTF-8）直接读取，不调用模型。

## 服务配置

在 `examples/agent_service/.env` 设置，修改后重启 AgentScope 服务：

```dotenv
MINERU_LOCAL_URL=http://127.0.0.1:8001
# 自部署服务设置了 API key 时才需要
MINERU_LOCAL_TOKEN=
# 从 MinerU 控制台申请；不要填模型供应商的 Key
MINERU_API_TOKEN=
```

Token 仅保存在服务端，不返回页面、不放入文档元数据。
本次未安装 MinerU 推理运行时或下载其模型权重；需在独立推理环境部署后使用。
例如在符合 MinerU 要求的独立环境中安装 `mineru>=4,<5`，配置运行时与模型，再启动：

```sh
mineru-kit api-server --host 127.0.0.1 --port 8001 --tier standard
```

服务位于另一台主机时调整地址，防火墙限制访问并配置认证。不要占用 AgentScope 的 8000 端口。
部署版本需支持 `GET /v1/health` 和 ZIP 输出；接口不兼容会明确报错。

视觉 PDF 渲染依赖：`pypdfium2>=4,<6`、Pillow。不会执行 PDF 脚本，不将本地文件路径交给大模型。

## 边界与安全

- 单文件 50 MB；视觉 PDF 上限可选 1–200 页，超限整体拒绝，不截取前几页冒充完成。
- MinerU 云端自身限制仍适用。每次解析总超时 15 分钟；失败可手动重试，可能再次计费。
- 本地模式拒绝跨域上传地址；云端签名上传/下载不携带 MinerU Token。
- ZIP 只在内存读取，限制展开大小与文件数，拒绝路径穿越。
- 原文件、Markdown、图片、JSON 保存在私有 MinIO；每次下载重新检查原文件 ACL。
- Markdown 页面显示源码预览，避免第三方图片/HTML 造成隐式外联或脚本执行；相对资源可在产物列表下载。
- 视觉输出保留页码和原始页面图，LLM 输出截断/空内容不进入成功状态。
- MinerU 输出的结构 JSON 同时保留；只有明确的页码标记才用于分块页码，不猜测页码。
- Markdown 标题边界进入分块 metadata，继续使用知识库设置的分块长度与重叠参数。
- 本实现使用嵌入式索引 worker。独立 worker 必须显式注入同一个解析回调，否则带解析配置的文档会报错，不降级。

接口依据：
- https://github.com/opendatalab/MinerU/blob/master/docs/en/usage/http_api.md
- https://mineru.net/apiManage/docs
