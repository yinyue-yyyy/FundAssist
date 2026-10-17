# 基金公告运营助手

一个 Python + Streamlit 单应用：将基金公告转化为有原文依据、可编辑的客服与 App 运营材料。

## 本地运行（推荐）

需要 Python 3.12、能够访问 OpenAI API 的网络，以及有模型调用权限和额度的 API key。

### Windows 快速启动

首次安装，在项目目录运行：

```powershell
.\setup.ps1
```

脚本创建 `.venv`、安装锁定版本的四个直接依赖，并在不存在时创建秘密配置文件。已有配置不会被覆盖。若未自动找到 Python：

```powershell
.\setup.ps1 -PythonPath C:\path\to\python.exe
```

编辑 `.streamlit/secrets.toml`，只在本地填写：

```toml
OPENAI_API_KEY = "你的 API key"
DEMO_ACCESS_CODE = ""
```

日常启动：

```powershell
.\start.ps1
```

打开终端显示的本地地址，默认为 <http://localhost:8501>。停止时在终端按 Ctrl+C。启动不会重复安装依赖。

### 通用命令（Windows / macOS / Linux）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS / Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

把 `.streamlit/secrets.toml.example` 复制为 `.streamlit/secrets.toml` 并填入密钥，或设置服务器环境变量 `OPENAI_API_KEY`。随后：

```bash
python -m streamlit run app.py
```

缺少密钥时仍可打开页面、查看原始案例和已保存的真实分析结果。修改输入后需配置密钥，才能提取新事实或生成新材料。

## 5 分钟体验

1. 默认选择「案例 B · 大额申购限制」，直接查看已保存的事实和运营材料，无需调用 API。
2. 在「公告与事实」核对限额、日期、合并口径，展开「查看事实依据」核查页码和摘录，点击「确认并保存事实」。
3. 切换到「用户情境」，默认填写定投 20,000 元。实际执行日期及其他业务未知时留空；已确认没有其他申请时才填 0。点击「保存用户情境」。
4. 点击「分析用户影响并生成材料」，再切换到「运营材料」查看关键结论，展开计算依据和待核实事项。原始输入再次生成仍复用结果；修改情境后点击生成才调用 API。
5. 在客服、FAQ、App 标签页编辑文案；核对后勾选人工确认，下载 Markdown 和 JSON 记录。侧栏仅展示模型信息与配置状态，不展示费用、token 或请求统计。
6. 切换 A、C 重复操作。案例 C 默认不将持有份额资格或分红方式视为已核实；在资格未知时，750 元保留为条件性计算。

修改表单后先点击对应保存按钮。已保存输入发生变化时旧材料标记过期；编辑文案后清除审核标记。普通编辑、切换标签和下载不会额外调用模型。

## 输入与真实 AI

- 内置案例输入位于 `data/cases.json`；已有真实模型结果从 `output/real-runs/` 读取。自动选择最新完整且与原公告、产品资料和默认情境一致、通过校验的记录；保留原文件，不冒充本次新调用或人工审核。
- 支持文字型 PDF（10 MB、20 页内）或粘贴正文；公告加产品资料最多 12,000 字符，超限不截断。
- 对多公告文件先选页、调整正文；修改后的正文标记为人工文本。扫描件不做 OCR。
- 一次新输入最多两次生成请求：提取事实、生成材料。修改用户金额时复用已确认事实，只需再次生成材料。
- 模型固定为 `gpt-5.4-mini-2026-03-17`，关闭额外推理，输出上限 2,500 token，60 秒超时，不自动重试或升级模型。
- 内置案例原始输入在不同会话均可读取本地历史结果，不消耗 API 额度。修改公告后点击提取、修改已确认事实或用户情境后点击生成，按新输入调用 API；同会话再次提交相同输入则复用缓存。
- 关键金额使用 `Decimal` 计算；引用逐字核验。仅当引文在同来源的唯一页面匹配时允许修正模型给错的页码，修正详情写入运行记录。

## 测试与真实运行记录

离线测试不消耗 API 额度，测试替身只存在于 `tests/`：

```bash
python -m unittest discover -s tests -v
```

读取并校验全部三个案例已保存的两次真实运行结果（不调用 API、不覆盖原记录）：

```bash
python scripts/run_cases.py --repeat 2
```

只读取一个案例：

```bash
python scripts/run_cases.py --case B --repeat 1
```

历史结果位于 `output/real-runs/时间戳/`，包含输入、模型实际输出、token、费用估算、提示词版本、运行状态及 Markdown。脚本直接读取已有记录；缺少匹配的完整结果时报告失败，不自动调用 API。成功和失败的历史文件均保留。结果仍需业务核对，命令成功不等于人工审核完成。

实际验证摘要见 `output/验证报告.md`。评审版设计思路见 [DESIGN.html](DESIGN.html)，涵盖问题分析、产品方案、AI 应用、验证结果和版本局限，支持离线阅读与打印；简要说明保留在 `DESIGN.md`。HTML 已区分历史验收和本次复核（63 项离线测试、6 份历史结果只读校验，无新增模型调用），原始复核输出位于 `output/design-review/`。

## 费用和保存方式

开发验证和演示费用目标合计 2 美元，不是跨重启、跨部署或账户级硬限额。单个进程最多 50 次生成请求；已知进程费用达到目标后停止新请求，失败但未返回用量的费用需核对账单。

费用估算采用每百万输入 $0.75、缓存输入 $0.075、输出 $4.50 的标准文本价格，不包含托管、Codex 开发及账户其他应用消费。最终以 OpenAI 账单为准。

内置案例的历史结果保存在磁盘，可跨会话读取。新输入生成的材料和人工编辑只保存在当前会话，刷新、关闭页面或服务重启可能丢失，请下载保存。读取历史记录不会将其费用计入本会话新增费用。秘密配置已被 `.gitignore` 排除；不要把真实客户信息或密钥放入公开仓库。

## 可选公网部署（Streamlit Community Cloud）

1. 将源码、`data/cases.json`、需要复用的虚构案例记录 `output/real-runs/` 和依赖文件推送至自己的 GitHub 仓库；确认未提交 `.streamlit/secrets.toml`、`.venv/` 或真实客户资料。
2. 在 Streamlit Community Cloud 新建应用，选仓库、分支、入口 `app.py`，Python 版本选 3.12。
3. 在平台 Secrets 中填入 `OPENAI_API_KEY` 和非空的 `DEMO_ACCESS_CODE`，再部署。体验码通过单独渠道提供给评审。
4. 用实际体验网络验证页面、真实分析和 Markdown 下载。平台睡眠或重启会重置会话及进程计数。

部署不需要数据库、Redis、Docker、域名或前端构建。若账号、平台或网络受阻，使用上述本地运行方式及实际截图交付。

## 常见问题

- **模型无权限／不可用：**核查 OpenAI 项目权限与指定模型，不会自动换模型。
- **连接失败：**先确认电脑可以访问 OpenAI API；检查网络和代理，避免反复重试产生额外费用。
- **模型结果校验失败：**页面会保留输入与失败记录。先核查正文、引文、金额与日期，必要时手动重试；不会显示未通过校验的草稿为成功结果。
- **达到次数上限：**先核对 API 账单，再由演示负责人决定后续运行；应用不把重启视为恢复预算。

参考：[Streamlit 部署](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy)、[OpenAI 模型与价格](https://developers.openai.com/api/docs/models/gpt-5.4-mini)。
