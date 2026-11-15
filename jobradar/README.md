# JobRadar V0.1

用于个人求职信息发现与人工核实。GitHub Pages 直接读取 jobs.json，无需服务端。

## 本地运行（Windows PowerShell）

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements-jobradar.txt
.\.venv\Scripts\python.exe -m unittest discover -s scripts -p 'test_*.py'
node scripts/test_jobradar_page.cjs
.\.venv\Scripts\python.exe scripts/run_jobradar.py
```

最后一条命令依次运行列表采集与正文/岗位表解析。任一步失败，最终退出码为 1，但其他来源和成功正文照常保存。不自动提交或推送。

预览：在仓库根目录执行 `python -m http.server 8765 --bind 127.0.0.1`，浏览器访问 http://127.0.0.1:8765/jobradar/ 。结束后 Ctrl+C 关闭预览。

## 来源和解析能力

- sources.json 配置官方来源、公告 URL 范围及已验证正文区域的 CSS class。
- 默认从栏目页提取公告链接。kind=article 是已发现官方公告详情的定点监测，不代表自动发现全站岗位；使用真实页面 title，不编造岗位标题。
- 读取静态 HTML 正文，遇到登录页、验证码或限制不尝试绕过。4xx 和证书问题不重试。
- XLS 岗位表仅支持可识别的中文表头，支持两行表头和真实合并单元格。每条岗位保留附件 URL、工作表和行号。文件上限 5 MB，不执行宏。报名表/简历表不下载。
- 暂不支持 PDF、DOC、DOCX、XLSX 岗位表；识别到需要解析但不支持的岗位附件明确报告失败，不宣称解析完成。普通未知附件保留链接待人工检查。
- 现有 jobs 字段和 URL 哈希 ID 保持兼容。新增正文证据、body_positions、attachments.positions 及阶段健康状态。

## 初筛含义

“优先核实”仅说明岗位行出现 C++、Qt、OpenGL、OCCT 或工业软件技术线索；CAD/CAM 制图操作不单独触发优先核实。

“明确不符合”用于已识别的招聘流程通知，或逐岗位明确博士学历要求与已知硕士学历不符。多岗位公告不因其他岗位要求博士而整体排除。不输出“明确符合”，专业、年龄、资格、具体经验和招聘时效仍须人工核实。

网页的“技术岗位优先核实”排除已提取到明确过期日期的公告；未提取截止日期不代表仍在招聘。附件岗位继承所属公告期限，不能单独作为当前可投递岗位。

失败时不会保留可用于技术优先筛选的旧岗位结果；旧正文片段只供参考并注明可能过时。Actions 上传两个阶段的日志和数据，采集失败状态不会被后续上传、数据更新掩盖。

完整验证记录见 COLLECTION_VALIDATION.md。未做远端 Actions 验证，当前改动未推送。


## 求职看板

页面默认显示“优先核实”，只呈现具有已解析技术岗位线索且未明确过期的公告。可切换全部公告、收藏、投递进度、来源健康，按来源、期限和公告类型筛选。搜索会覆盖已成功解析的岗位条件。

星号收藏的是整份公告。投递进度与备注按公告 ID 保存，供个人跟进；系统不会提交求职申请。记录使用 `jobradar.personal.v1` 本地存储键，不写入公开 jobs.json，不向服务器上传。记录只在当前浏览器的当前网站地址下可用，本地预览与 GitHub Pages 之间需要用导出/导入转移。

个人记录可导出 JSON 备份并导入合并；同一公告采用导入记录。导入先验证全部字段，无效文件不会改变原记录。损坏的本地存储不会自动被覆盖；无法持久化时提示暂存内存及备份。不要将包含个人备注的备份提交到公开仓库。

前端文件为 index.html、style.css、ui-core.js 和 app.js，无构建步骤和外部 CDN 依赖。静态页面测试用 Node 执行真实渲染逻辑，覆盖本地记录、筛选与输入转义。服务端采集脚本和 jobs.json 数据结构保持兼容。


## 测试分支发布（尚未获准正式发布）

数据先经 prepare_jobradar_release.py 检查批次、26 小时新鲜度和失败状态。publish_jobradar_data.py 仅允许 codex/jobradar-monitor-validation 分支，明确拒绝 main 和开发分支；只有两个数据文件在白名单内，相同 Git blob 不创建提交。发布采用一次 tree/commit/ref 更新，两份文件不会分步生效；分支变化或验证失败时停止，不强制覆盖。

Windows 命令行发布需要在进程环境提供 JOBRADAR_GITHUB_TOKEN，不写凭据文件或日志。默认只读计划；只有显式 --push 才更新测试分支。当前 Codex 的 GitHub 连接和本机 Git 凭据相互独立，连接工具发布成功不代表 Windows 已具备无人值守凭据。

开发分支的 workflow 已准备为纯测试、contents: read，删除旧定时采集和数据写回。该修改在正式批准进入 main 前，不影响远端 main 的旧定时工作流。正式发布前需要先批准关闭旧定时写入，再决定代码合并和数据更新方式。

页面最小增量：新增摘要区域，读取 daily-summary.json；校验与 jobs.json 的批次、更新时间、失败状态一致。摘要缺失、混批或错误状态不一致时显示不可用，原公告列表继续工作，不将旧摘要当作当前结果。
