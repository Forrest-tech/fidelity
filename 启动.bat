@echo off
REM ============================================================
REM  Fidelity - 转换保真度评测系统  一键启动（Windows）
REM
REM  双击本文件即可启动。会自动：
REM    1. 检查 Python 依赖（缺什么装什么）
REM    2. 构建前端（若未构建或源码有更新）
REM    3. 启动后端并托管前端
REM    4. 打开浏览器到 http://127.0.0.1:8000
REM
REM  重复双击不会重复启动：服务已在跑时只打开浏览器。
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
set ROOT=%CD%
set PORT=8000
set URL=http://127.0.0.1:%PORT%

echo.
echo  ==========================================================
echo    Fidelity  转换保真度评测系统
echo    源文件 与 Markdown 转换产物 逐行对账
echo  ==========================================================
echo.

REM ---------- 1. 找 Python ----------
REM 优先级：项目内 .venv > .venv（backend下）> 系统 python / py
REM 关键：依赖装在虚拟环境里，系统的 python 往往没有 —— 直接用系统 python
REM       会误判成「缺依赖」然后去重装，浪费时间还可能装错地方。
set PY=

if exist ".venv\Scripts\python.exe" (
  set PY=.venv\Scripts\python.exe
) else if exist "backend\.venv\Scripts\python.exe" (
  set PY=backend\.venv\Scripts\python.exe
) else (
  where py >nul 2>nul && set PY=py
  if not defined PY (
    where python >nul 2>nul && set PY=python
  )
)

if not defined PY (
  echo  [错误] 没找到 Python。
  echo         请先安装 Python 3.11 以上版本，安装时勾选 "Add to PATH"。
  echo.
  pause
  exit /b 1
)
echo  [1/4] Python: %PY%

REM ---------- 2. 依赖 ----------
REM 用 pymupdf 而非旧的 fitz —— fitz 已被上游废弃，导入会打警告
echo  [2/4] 检查依赖 ...
%PY% -c "import fastapi, uvicorn, pymupdf" >nul 2>nul
if errorlevel 1 (
  if not "%PY%"=="py" if not "%PY%"=="python" (
    REM 项目内 venv 存在但仍缺依赖 -> 多半是装到一半断了，让它自己修
    echo        项目内虚拟环境依赖不完整，正在修复...
    %PY% -m pip install -r backend\requirements.txt --quiet
    if errorlevel 1 (
      echo  [错误] 依赖安装失败，请检查网络。
      pause
      exit /b 1
    )
    echo        修复完成。
  ) else (
    REM 找到的是系统 python —— 绝不能往用户全局环境里装包
    echo.
    echo  [错误] 系统的 %PY% 里没有本项目依赖。
    echo.
    echo         依赖必须装在独立虚拟环境里，不要污染系统 Python。
    echo         请按下面任意一种方式处理：
    echo.
    echo         方式一（推荐）创建项目内环境后重试：
    echo             cd "%ROOT%"
    echo             %PY% -m venv .venv
    echo             .venv\Scripts\pip install -r backend\requirements.txt
    echo.
    echo         方式二 若你已有可用环境，让它先激活再双击本文件。
    echo.
    pause
    exit /b 1
  )
) else (
  echo        依赖已就绪。
)

REM ---------- 3. 前端 ----------
set DIST=web\dist\index.html
if exist "%DIST%" (
  echo  [3/4] 前端已构建，跳过。
) else (
  echo  [3/4] 首次运行，正在构建前端（需数分钟）...
  where node >nul 2>nul
  if errorlevel 1 (
    echo  [错误] 没找到 Node.js，无法构建前端。
    echo         请安装 Node.js 18 以上： https://nodejs.org
    echo         装完后重新双击本文件。
    echo.
    pause
    exit /b 1
  )
  pushd web
  call npm install --silent
  call npm run build
  popd
  if not exist "%DIST%" (
    echo  [错误] 前端构建失败。
    pause
    exit /b 1
  )
  echo        前端构建完成。
)

REM ---------- 4. 启动 ----------
echo  [4/4] 启动后端 ...
echo.
echo  ----------------------------------------------------------
echo   启动中，首次启动约需 5-10 秒。
echo   启动后请在浏览器访问：  %URL%
echo   关闭本窗口即停止服务。
echo  ----------------------------------------------------------
echo.

REM 等服务起来再开浏览器
start "" cmd /c "timeout /t 8 >nul & start "" %URL%"

cd backend
%PY% -m scripts.serve

echo.
echo  服务已停止。
pause
