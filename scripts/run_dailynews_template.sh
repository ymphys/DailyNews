#!/bin/bash
# 加载私有环境变量
source /your/path/to/DailyNews/.dailynews_env

cd /your/path/to/DailyNews || exit 1
/opt/homebrew/bin/uv run main.py >> /your/path/to//DailyNews/logs/cron.log 2>&1