@echo off
rem LWA 交替抓取：抓新收藏 → 补评论 → 补以前的收藏 → 补评论 …，同时另开实时进度黑框。关掉抓取窗口即停。
cd /d "%~dp0.."
start "LWA 实时进度" cmd /k python -m link_brain watch
start "LWA 交替抓取" cmd /k python -m link_brain crawl
