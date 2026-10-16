@echo off
rem LWA 实时进度：另开一个黑框，每 2 秒刷新（只读本机文件，不碰号）。关窗即退出。
cd /d "%~dp0.."
start "LWA 实时进度" cmd /k python -m link_brain watch
