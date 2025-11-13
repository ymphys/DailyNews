#!/bin/bash
# 加载私有环境变量
source /Users/zhangjiabao/LLM_Dev/DailyNews/.dailynews_env

cd /Users/zhangjiabao/LLM_Dev/DailyNews || exit 1
/opt/homebrew/bin/uv run main.py >> /Users/zhangjiabao/LLM_Dev/DailyNews/logs/cron.log 2>&1