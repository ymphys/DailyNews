# DailyNews 📰

[![Build](https://img.shields.io/badge/build-passing-brightgreen.svg)](#)
[![Python](https://img.shields.io/badge/python-3.12+-3776AB.svg?logo=python&logoColor=white)](#)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](#)
[![Coverage](https://img.shields.io/badge/coverage-90%25-blue.svg)](#)

一个轻量级的新闻助手，可以从多个地区和语言收集最新头条以及针对自定义话题的最新新闻，规范化处理结果，并生成新闻摘要。提供可重复的、基于查询的新闻摘要。

## ✨ 特性

- 🌍 支持多语言和多地区新闻源
- 🔍 可配置的查询驱动收集系统
- 📊 自动生成 Markdown 格式的摘要
- ⚡ 内置指数退避的可靠 HTTP 调用
- 🔐 安全的环境变量管理

## 🚀 快速开始

### 前置要求

### 安装
1. **克隆仓库**
```bash
git clone https://github.com/ymphys/dailynews.git
cd dailynews
```

2. **创建并激活虚拟环境**
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

3. **安装依赖**
```bash
uv pip install -e .
```

### 配置

1. 设置环境变量：
   - 在项目根目录创建 `.env` 文件
   - 添加 `NEWSAPI_KEY=your_api_key_here`

2. 配置查询主题：
   - 编辑 `config/run_state_topics.json`
   - 定义您感兴趣的语言和关键词
### 前置要求

- Python 3.12 或更高版本
- NewsAPI.org API 密钥
- uv 包管理器

### 安装

1. **克隆仓库**
```bash
git clone https://github.com/ymphys/dailynews.git
cd dailynews
```

2. **安装依赖并创建虚拟环境**
```bash
uv sync
```

### 配置

1. 设置环境变量：
```bash
export NEWSAPI_KEY=your_api_key_here  # macOS/Linux
# 或
setx NEWSAPI_KEY your_api_key_here    # Windows
```

2. 配置查询主题：
   - 编辑 `config/run_state_topics.json`
   - 定义您感兴趣的语言和关键词

## 💡 使用方法

### 基本使用

运行收集器：
```bash
uv run main.py --topics config/run_state_topics.json --output data/$(date +%Y%m%d)
```

### 命令行选项

| 选项 | 描述 |
|------|------|
| `--topics PATH` | 主题配置文件路径 |
| `--output DIR` | 输出目录（将生成 JSON、CSV、Markdown） |
| `--max-pages N` | 覆盖默认分页深度 |
| `--since YYYY-MM-DD` | 仅获取指定日期后的文章 |
| `--dry-run` | 预览将执行的查询而不调用 API |

### 自动化工作流

1. 更新配置文件中的关键词
2. 确保环境变量已设置
3. 运行脚本
4. 在 `data/<YYYYMMDD>/` 查看生成的摘要

> 💡 提示：可以通过 cron 作业或 GitHub Actions 实现自动更新

## 🛠 技术栈

- **核心**
  - Python 3.12+
  - Requests (带指数退避)
  - python-dotenv

- **可选组件**
  - Pydantic / dataclasses (数据验证)
  - Rich / Typer (CLI 增强)

> 📦 完整依赖列表见 `pyproject.toml`

## 🗺 路线图

- [ ] 多提供商适配器 (Guardian API, GDELT, RSS)
- [ ] 重复内容检测
- [ ] 命名实体识别自动标记
- [ ] Web 仪表板 (Streamlit/Next.js)
- [ ] GitHub Actions 自动构建 + 通知

## 🤝 贡献

欢迎贡献和建议！请先开 issue 讨论您想要改变的内容。

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件
