# GitHub File Sync Project

此项目通过 GitHub Actions 每天自动同步远程 GitHub 仓库中的文件到当前仓库。它经过高度优化，稳定、高效且智能，能够处理各种复杂情况。

## ✨ 核心特性

- **🚀 极速同步**：基于 `asyncio` 和 `aiohttp` 的异步并发架构，支持同时处理多个文件，速度飞快。
- **🛡️ 智能容错**：
    - **自动重试**：遇到网络波动自动重试。
    - **URL 自动修正**：自动修复错误的 GitHub 链接（如包含 `/blob/` 或 `/refs/heads/` 的链接）。
    - **JSON 安全校验**：同步 `.json` 文件前会自动校验格式，防止因源文件损坏导致本地配置被覆盖。
- **📦 全面兼容**：
    - **二进制支持**：完美支持 `.jar`, `.zip`, 图片等二进制文件，自动检测文件类型，防止损坏。
    - **文本标准化**：自动处理不同系统的换行符（CRLF/LF），避免 Git 出现虚假变更。
    - **BOM 支持**：自动处理带 BOM 头的 `config.json` 文件（兼容 Windows 记事本编辑）。
- **🔒 安全可靠**：
    - **路径防护**：内置路径遍历攻击检测，防止恶意配置。
    - **并发控制**：限制并发请求数，防止触发 GitHub API 速率限制。

## 📂 目录结构

- `.github/workflows/sync.yml`: GitHub Actions 自动化工作流配置。
- `sync_script.py`: 核心同步脚本（Python）。
- `config.json`: 配置文件，定义同步规则。
- `requirements.txt`: Python 依赖列表。

## 🚀 如何使用

1.  **Fork 或 Clone 此仓库**。

2.  **配置同步规则 (`config.json`)**：
    修改 `config.json` 文件，添加你需要同步的文件列表：
    ```json
    {
        "files": [
            {
                "remote_url": "https://raw.githubusercontent.com/tushen6/Tomorrow/master/lmw.json",
                "local_path": "data/lmw.json"
            },
            {
                "remote_url": "https://github.com/username/repo/blob/main/spider.jar",
                "local_path": "jar/spider.jar"
            }
        ]
    }
    ```
    *   **自动创建**：如果本地路径不存在，脚本会自动创建文件夹和文件。
    *   **智能链接**：你可以直接复制浏览器地址栏的链接（包含 `/blob/`），脚本会自动转换为下载链接。

3.  **提交更改**：
    ```bash
    git add .
    git commit -m "Update config"
    git push
    ```

4.  **自动运行**：
    GitHub Actions 会在每天 **UTC 00:00 (北京时间 08:00)** 自动运行。
    你也可以在仓库的 "Actions" 页面手动点击 "Run workflow" 立即触发。

## 🔑 私有仓库支持 (可选)

如果你需要同步**私有仓库**的文件，或者需要更高的 API 速率限制：

1.  创建一个 [Personal Access Token (PAT)](https://github.com/settings/tokens)。
2.  在仓库设置中添加 Secret：`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`。
    *   Name: `GH_TOKEN`
    *   Value: 你的 Token 内容
3.  脚本会自动读取此 Token 进行认证。
    *   **注意**：同步公开仓库文件**不需要**配置此项。

## 🛠️ 本地开发/测试

如果你想在本地运行脚本：

1.  安装依赖：
    ```bash
    pip install -r requirements.txt
    ```
2.  运行脚本：
    ```bash
    python sync_script.py
    ```
