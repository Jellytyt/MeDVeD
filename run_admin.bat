@echo off
powershell -Command "Start-Process -Verb RunAs -FilePath python -ArgumentList 'app.py' -WorkingDirectory '%~dp0'"
