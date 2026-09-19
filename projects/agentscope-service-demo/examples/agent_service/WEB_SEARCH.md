# 联网搜索与网页读取

`network_tools.py` 提供 `web_search` 和 `web_fetch`，挂载在现有后端中，
通过无状态 HTTP MCP 调用，不需要独立进程。也支持单独运行 STDIO 模式。
聊天模型继续使用会话原有配置。搜索单独调用 DeepSeek 官方的
`https://api.deepseek.com/anthropic/v1/messages`，使用 `deepseek-v4-flash`
及 `web_search_20250305` 服务端工具；需要有效的 DeepSeek 凭据和额度。
只接受结构化搜索结果，不把辅助模型生成的回答当作搜索证据。

## 配置

服务读取 `WEB_SEARCH_CONFIG` 指定的 JSON 文件，默认：
`/workspace/data/agentscope/secrets/web-search.json`。
文件格式为 `{"api_key": "替换为有效密钥"}`；目录权限 700，文件权限 600。
也支持通过 `DEEPSEEK_API_KEY` 环境变量覆盖。不要把密钥提交到代码库，
也不要填入 MCP 描述、参数或用户可见的工具结果。更新文件后下一次搜索生效。

在管理员的自定义 MCP 中创建：

- 名称：`web-search`
- 传输：`http`，`stateful: false`
- 地址：`http://127.0.0.1:8000/internal/web-search/mcp`
- Headers：`{"X-User-ID": "wei"}`（管理员身份，沿用现有门户鉴权）
- 超时：`timeout: 120` 秒（自定义 MCP API 支持 1–180 秒，默认 20 秒）

测试连接应列出两个工具。管理员在会话的 MCP 管理中从库添加该 MCP；普通用户
须先在“访问授权”中获得该 MCP，再在会话中勾选。首次部署对 portal.py 的
管理员会话 MCP 选择持久化修复及 HTTP 挂载需要重启后端，之后新增该 MCP 无需重启。
内部 HTTP 端点受门户鉴权保护，普通用户通过已授权 MCP 调用，不直接开放端点。
工具调用及结果沿用现有执行详情与审计；搜索内部辅助模型的 token 用量
不并入聊天模型 token 统计，以 DeepSeek 账单为准。

## 使用和边界

实时信息先搜索，需要核实细节时再抓取来源正文，回答附来源链接。
搜索词会发送到 DeepSeek 官方服务。网页获取不携带搜索密钥或浏览器 Cookie。
网页文本作为不可信资料处理，不应执行网页里的指令。

网页获取仅允许公开 HTTP(S) 标准端口，校验每一跳 DNS 并绑定已验证 IP，
拦截内网、回环、保留地址及携带登录凭据的 URL；限制跳转、时间、下载量和正文长度。
不执行 JavaScript，不支持登录页面或 PDF；反爬、动态内容可能使网页无法获取。
正文提取移除脚本、导航及常见隐藏节点，不是完整浏览器渲染。

## 验证

在此目录执行 `../../.venv/bin/python -m unittest test_network_tools -v`。
离线验证接口协议、结构化结果、失败信息、凭据不回显、中文提取、私网地址与跳转限制。
实际网络验证需单独调用搜索/网页工具，会产生搜索接口用量。
