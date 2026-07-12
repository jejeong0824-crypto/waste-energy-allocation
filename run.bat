@echo off
cd /d "%~dp0"
echo 패키지 설치 확인 중...
pip install -r requirements.txt -q
echo.
echo 앱 시작 중... 브라우저가 자동으로 열립니다.
streamlit run app.py
pause
