# 工具集：维修工单处理 + 视频英文化

一个网页入口，左侧按分组切换：

| 分组 | 页面 | 作用 |
|---|---|---|
| 工单处理 | 🔧 工单处理 | 海外维修商原始工单（Excel）自动翻译、分类、标准化 |
| 工单处理 | 🏆 重点产品故障排名 | 上传**已整理好的工单**，生成 BU / 型号 / 故障数量 / TOP 故障类型占比 |
| 视频工具 | 🎬 视频英文化 | 中文视频 → 外语字幕 + 配音（ASR / 翻译 / TTS / 烧录） |

**启动（Windows 最省事）**：双击 **`run.bat`**，浏览器会自动打开，不用碰命令行。
其它方式：`streamlit run main.py`（入口是 `main.py`，不是 `app.py`）

## 支持区域

| 区域 | 服务商 | 原始表语言 |
|---|---|---|
| 澳洲 | PAU | 英文 |
| 韩国 | SK | 韩文 |
| 韩国 | KOLON | 韩文 |
| 日本 | NGK | 日文 |
| 日本 | ITC | 日文 |

## 功能

- **自动翻译**：故障描述、维修详情、备注 → 简体中文
- **故障分类**：输出统一的「故障类型（一级）」
- **类别判定**：DOA / 维修（保内）/ 维修（保外）/ 无异常（NFF）/ 重复 / 二返 / 三返
- **返修识别**：按 SN + 日期判定「重复」「二返（重现/新故障）」「三返（重现/新故障）」，支持跨批次（断点续跑）判定
- **标记双写**：返修标记同时写入「类别」和「处理方式」两列（处理方式形如 `重复 / 补发配件`，不丢原处理方式，可直接按处理方式筛选返修单）
- **型号归一化**：各国型号写法统一为澳洲格式（如 `X50Ultra` → `X50 Ultra`）
- **并发处理**：默认 4 线程，可在侧栏调节（1–8）
- **断点续跑**：处理中断后重新上传同一文件，自动跳过已处理工单
- **二返率统计**：对已处理结果按 SN + 日期重算 重复/二返/三返，输出型号二返率（见下文）
- **重点产品故障 TOP3**：下载的 Excel 自动带第 2 个 sheet，按 BU 汇总重点型号的故障数量与 TOP 故障类型占比（见下文）

## 重点产品故障 TOP3

下载工单时（「导出已处理部分」/「下载全部已处理」），Excel 会写入 **2 个 sheet**：

| sheet | 内容 |
|---|---|
| 第 1 个 | 工单明细（原有内容不变） |
| 第 2 个 `重点产品故障TOP3` | 按 BU 汇总的重点型号故障表 |

sheet2 的 5 列与《重点产品故障数量和类型.xlsx》一致：

| 列 | 含义 |
|---|---|
| 类别 | 产品 BU（扫地机 / 洗地机 / 吸尘器…），同 BU 单元格纵向合并 |
| 型号 | 该 BU 内故障数前 N 的型号（N 默认 5，页面上可调） |
| 故障数量 | 该型号的工单数（只算纳入统计的类别） |
| 占比 | 该型号 ÷ 该 BU 全部工单数（整数百分比，如 14%） |
| TOP故障类型（单机型占比） | `1.拖布电机不良--15%` 换行 `2.LDS组件不良--13%`…（至多 3 条，N 可调） |

口径说明：

- **统计范围**：默认**只算「类别」= 维修（保内）+ DOA**，即排除 维修（保外）/ 无异常（NFF）/ 重复 / 二返 / 三返。页面上有「只统计这些类别」多选框，清空则统计全部类别
- 「占比」的分母是**该 BU 的全部工单数**（同样只算纳入范围的类别），所以同一 BU 内各型号占比之和小于 100%，属正常（参考表也是这个口径）
- 「TOP故障类型」里的百分比分母是**该型号自身的工单数**，不是整个 BU
- 「未发现故障 / NFF」计入故障数量，但不参与故障类型排名
- 型号大小写、空格写法差异会自动合并（`x50  ultra` 与 `X50 Ultra` 视为同一型号）
- BU 为空时按型号前缀（`core/config.py` 的 `PRODUCT_BU_MAP`）自动推断；推断不出的归入「未分类」，可在 `core/config.py` 里补一行映射

页面底部「🏆 重点产品故障 TOP3」区块可直接预览这张表，也可单独下载；模型数 / TOP 条数 / 类别范围同时作用于预览和导出。

左侧「工单处理 → 🏆 重点产品故障排名」是**独立页面**，与主流程解耦：上传主流程导出的「优化后工单.xlsx」（或任意含 型号 / 产品BU / 故障类型 / 类别的表）即可出排名，也可直接读当前区域的已处理记录；支持按 BU、按类别多选筛选，下载单 sheet 排名表或「排名 + 工单明细」双 sheet 文件。

命令行用法：

```bash
python core/key_products.py 已处理工单.xlsx -o 重点产品故障TOP3.xlsx --top-models 5 --top-faults 3
```

## 二返率统计

页面底部「📊 二返率统计」区块，可对**任意已处理结果**做二次分析：

- 数据来源：当前区域的断点结果，或直接上传一份已处理工单（`.xlsx` / `.csv`）
- 窗口可调：重复判定窗口（默认 3 天，与工单处理规则一致；0 = 仅同日）、返修判定窗口（默认 90 天）
- 处理方式列：追加标记（默认，`重复 / 补发配件`）/ 覆盖原值 / 不改，三种模式可选
- 输出：总工单数 / 返修数 / 二返数 / 重复数 指标卡，以及「明细报告」「型号二返率」「全量结果」三张表，均可导出 Excel
- 明细报告：重复排最前、其后按 二返 → 三返 归组，支持「全部 / 仅重复 / 仅二返 / 仅三返」筛选

判定规则：同 SN 日期间隔 ≤ 3 天 → 重复（3 天内的多次提交只算一次返修，不会虚增返次）；
同 SN 在返修窗口内的历史工单，第 2 次 → 二返、第 3 次 → 三返，故障类型与历史一致时加「（故障重现）」。

命令行同样可用（原 `2.py` 用法）：

```bash
python core/return_rate.py 已处理工单.xlsx -o 输出目录 --dup-days 3 --return-days 90
```

## 快速开始

> ⚠️ **入口必须是 `main.py`，不是 `app.py`。**
> 直接跑 `streamlit run app.py` 只会打开工单处理单页，**左侧没有导航、看不到另外两个工具**。

### 方式零：双击启动（Windows，推荐）

双击根目录的 **`run.bat`** 就行，不需要打开 Python 或命令行：

- 自动找 Python（`py` 启动器 → `PATH` 里的 `python` → 常见安装目录）
- 首次运行缺依赖会自动 `pip install`（约 1–3 分钟，只有第一次）
- 自动挑空闲端口（默认 8501，被占用就顺延），并自动打开浏览器
- 如果工具**已经在跑**，再双击只会把浏览器打开到已有页面，不会重复启动
- **关闭那个黑色窗口 = 停止服务**（已下载的文件不受影响）

也可以传端口：`run.bat 8600`。`start.bat` 保留为兼容入口，等价于 `run.bat`。

### 方式一：本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置密钥
cp .env.example .env
# 编辑 .env，填入 SILICONFLOW_API_KEY

# 3. 启动（注意是 main.py）
streamlit run main.py
```

> 视频工具还需要 **ffmpeg**（`winget install Gyan.FFmpeg` 或放 `video_en/bin/`）。
> 云端部署时仓库里的 `packages.txt` 会自动装 ffmpeg。

浏览器打开 http://localhost:8501

### 方式二：GitHub Codespaces

仓库已内置 `.devcontainer`，创建 Codespace 后会自动安装依赖并启动应用。

**配置密钥（二选一）**

1. **用 Codespaces Secret（推荐，一次配置长期生效）**
   仓库 → Settings → Secrets and variables → Codespaces → New repository secret
   名称填 `SILICONFLOW_API_KEY`，值为你的密钥。
   然后重启 Codespace（或 Rebuild Container）即可生效。

2. **在 Codespace 里手动建 .env**
   ```bash
   cp .env.example .env
   # 编辑 .env 填入密钥
   ```

> 代码读取顺序：系统环境变量优先，其次才是 `.env`。所以 Secret 方式不需要 `.env` 文件。

### 方式三：部署成网页链接（同事打开即用）

想让同事**不用装任何东西**就能用，部署到 Streamlit Community Cloud（免费）：

1. 打开 https://share.streamlit.io ，用 GitHub 账号登录
2. 点 **New app** → 选仓库 `robotcleaner/-`，Branch 选 `main`，Main file path 填 `main.py`
3. 点 **Advanced settings** → 在 **Secrets** 里填：

   ```toml
   SILICONFLOW_API_KEY = "sk-你的密钥"
   ```

4. 点 **Deploy**，等 1–2 分钟，得到形如 `https://xxxx.streamlit.app` 的链接

把那个 `https://xxxx.streamlit.app` 链接发给同事，对方浏览器打开就能用（无需 GitHub 账号、无需安装 Python）。

**注意**：
- 同一实例是共享的，多人**同时**处理时进度文件会互相干扰，建议同一时间一人使用；如需多人并行，可改为「会话隔离」模式。
- 翻译缓存不纳入仓库，线上首次运行会重新调用接口，产生少量费用。
- 免费实例闲置一段时间会休眠，首次打开需等十几秒唤醒。
- **视频工具在云端也能用，但很吃资源**：首次使用会下载识别模型（small 约 500MB），
  免费实例内存/CPU 有限，建议只处理 1~3 分钟的短视频；长视频请在本机跑。
- 视频工具的翻译密钥（智谱/百度）请在页面里填，不要写进仓库。

## 视频英文化

页面左侧切到「🎬 视频英文化」：

1. 上传中文视频（mp4 / mov / mkv 等）
2. 调参数：目标语言（英/日/韩）、字幕模式、识别模型、翻译后端、配音音色、分辨率
3. 点「开始生成」→ 实时进度 → 完成后在线预览 + 下载成品

处理链路：提取音频 → Whisper 识别中文 → 翻译 → edge-tts 配音并对齐时间轴 →
生成 ASS 字幕 → ffmpeg 烧录输出。

- 依赖：`ffmpeg`（必需）、`faster-whisper`、`edge-tts`（`pip install -r requirements.txt`）
- 翻译后端默认 MyMemory（免密钥）；想要质量更好可选智谱 GLM-4-Flash（免费，需 Key）
- 原桌面版（tkinter，支持多视频剪辑合成）仍保留在 `video_en` 之外的项目里，本仓库只含流水线模块

## 使用流程

1. 选择区域 / 服务商
2. 上传原始工单 `.xlsx`
3. 点「开始处理」，可随时暂停
4. 处理完成后下载「优化后工单.xlsx」

处理过程中每完成一行就写入 `state/partial_result_<区域>.csv`，中断后重新上传同一文件即可继续。

## 输出列

`工单号 / 区域 / 代理 / 型号 / 产品BU / 日期 / SN / 故障类型（一级）/ 处理方式 / 类别 / 故障描述 / 维修详情`（澳洲另有「备件消耗」）

## 目录结构

```
ticket_processor/
├── run.bat            ← 双击启动（推荐）
├── start.bat          ← 兼容入口，等价于 run.bat
├── launch.py          ← 启动器：查依赖 / 挑端口 / 开浏览器
├── main.py            ← 入口，左侧分组导航
├── app.py             ← 🔧 工单处理页
├── key_page.py        ← 🏆 重点产品故障排名页
├── video_page.py      ← 🎬 视频英文化页
├── core/              ← 业务模块（配置 / 处理器 / 统计 / 缓存）
├── data/              ← 数据与缓存（故障对照表、质保表、参考 Excel）
├── state/             ← 运行时状态（断点结果、翻译缓存；首次运行自动创建）
├── tools/             ← 调试 / 一次性脚本（含冒烟测试）
├── video_en/          ← 视频流水线模块（ASR / 翻译 / TTS / 字幕 / ffmpeg）
├── requirements.txt
├── packages.txt       ← 云端部署用（ffmpeg）
└── README.md
```

### 根目录（入口与页面）

| 文件 | 说明 |
|---|---|
| `run.bat` / `start.bat` | 双击启动，等价于 `streamlit run main.py` |
| `launch.py` | 启动器：依赖检查 / 自动装依赖 / 挑空闲端口 / 开浏览器 |
| `main.py` | **统一入口**（左侧分组切换三个页面） |
| `app.py` | 工单处理页面 |
| `key_page.py` | 重点产品故障排名页（上传已处理工单即可出排名） |
| `video_page.py` | 视频英文化页面 |

### `core/`（业务模块）

| 文件 | 说明 |
|---|---|
| `paths.py` | 统一目录定位（`data/`、`state/`），不依赖启动时的工作目录 |
| `processor.py` | 澳洲（AU）处理器 |
| `processor_kr.py` / `processor_kolon.py` | 韩国 SK / KOLON 处理器 |
| `processor_jp.py` / `processor_itc.py` | 日本 NGK / ITC 处理器 |
| `repeat.py` | 重复 / 二返 / 三返 分类器（生成「类别」列） |
| `return_rate.py` | 二返率统计（事后分析，含命令行） |
| `key_products.py` | 重点产品故障 TOP3（导出 Excel 的 sheet2，含命令行） |
| `date_refresh.py` | 断点文件日期口径修正 |
| `model_norm.py` | 型号格式归一化 |
| `batch.py` | 并发执行器 + 防抖落盘缓存 |
| `llm_client.py` | LLM 调用与缓存 |
| `config*.py` | 各区域列映射、提示词、字典表（含 `PRODUCT_BU_MAP`） |

### `data/` 与 `state/`

| 位置 | 内容 |
|---|---|
| `data/fault_mapping*.json` | 故障对照表缓存（各区域，翻译过的故障名） |
| `data/warranty_table.csv` | 型号质保年限表 |
| `data/产品故障分类中英韩日文.xlsx` | 日本 NGK 故障对照 |
| `state/partial_result_<区域>.csv` | 断点续跑结果（含真实工单数据） |
| `state/.cache.json` | LLM 翻译缓存 |

> 目录位置由 `core/paths.py` 统一解析，所以**双击 run.bat、命令行启动、云端部署**读到的都是同一份文件，不会因为工作目录不同而"找不到数据"。

### `tools/`（调试 / 一次性脚本）

`_smoke_test.py`（冒烟测试）、`debug_*.py`、`test_*.py`、`sk_*.py`、`config_au_optimized.py`、`processor_kr_enhanced.py` 等。
这些脚本**不参与网页运行**，只是排查问题时用，删掉也不影响主流程。

## 注意

以下文件**不纳入版本控制**（含密钥或真实工单数据），请勿提交：

- `.env`（API 密钥）
- `data/fault_mapping*.json`、`state/.cache.json`（翻译缓存，含工单文本）
- `state/partial_result*.csv`（处理结果，含真实 SN）
- `__pycache__/`

运行冒烟测试：

```bash
python tools/_smoke_test.py
```
