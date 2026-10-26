# 日韩澳维修工单处理系统

把海外维修商的原始工单（Excel）自动翻译、分类、标准化，输出统一格式的工单表。
基于 Streamlit + LLM（硅基流动 DeepSeek-V3）。

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
- **型号归一化**：各国型号写法统一为澳洲格式（如 `X50Ultra` → `X50 Ultra`）
- **并发处理**：默认 4 线程，可在侧栏调节（1–8）
- **断点续跑**：处理中断后重新上传同一文件，自动跳过已处理工单

## 快速开始

### 方式一：本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置密钥
cp .env.example .env
# 编辑 .env，填入 SILICONFLOW_API_KEY

# 3. 启动
streamlit run app.py
```

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

## 使用流程

1. 选择区域 / 服务商
2. 上传原始工单 `.xlsx`
3. 点「开始处理」，可随时暂停
4. 处理完成后下载「优化后工单.xlsx」

处理过程中每完成一行就写入 `partial_result_<区域>.csv`，中断后重新上传同一文件即可继续。

## 输出列

`工单号 / 区域 / 代理 / 型号 / 产品BU / 日期 / SN / 故障类型（一级）/ 处理方式 / 类别 / 故障描述 / 维修详情`（澳洲另有「备件消耗」）

## 目录说明

| 文件 | 说明 |
|---|---|
| `app.py` | Streamlit 界面与主流程 |
| `processor.py` | 澳洲（AU）处理器 |
| `processor_kr.py` / `processor_kolon.py` | 韩国 SK / KOLON 处理器 |
| `processor_jp.py` / `processor_itc.py` | 日本 NGK / ITC 处理器 |
| `repeat.py` | 重复 / 二返 / 三返 分类器 |
| `model_norm.py` | 型号格式归一化 |
| `batch.py` | 并发执行器 + 防抖落盘缓存 |
| `llm_client.py` | LLM 调用与缓存 |
| `config*.py` | 各区域列映射、提示词、字典表 |
| `_smoke_test.py` | 冒烟测试（不调用真实 LLM） |

## 注意

以下文件**不纳入版本控制**（含密钥或真实工单数据），请勿提交：

- `.env`（API 密钥）
- `.cache.json`、`fault_mapping*.json`（翻译缓存，含工单文本）
- `partial_result*.csv`（处理结果，含真实 SN）
- `__pycache__/`

运行冒烟测试：

```bash
python _smoke_test.py
```
