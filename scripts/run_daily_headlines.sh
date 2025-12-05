#!/bin/bash
# 加载私有环境变量
source /Users/zhangjiabao/Project/LLM_Dev/DailyNews/.dailynews_env

cd /Users/zhangjiabao/Project/LLM_Dev/DailyNews || exit 1
/opt/homebrew/bin/uv run main.py headlines >> /Users/zhangjiabao/Project/LLM_Dev/DailyNews/logs/cron.log 2>&1
