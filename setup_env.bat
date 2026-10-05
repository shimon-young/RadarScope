@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem ============================================================
rem  RadarScope - first-time environment setup (Windows)
rem
rem  What it does:
rem    1. Lets you pick a local Python 3.10 interpreter
rem    2. Creates a dedicated venv at RADAR_inference\env
rem       (deploy\start_server.bat picks this location up automatically)
rem    3. Installs PyTorch (CUDA 12.9 or CPU build) from the
rem       official PyTorch wheel index
rem    4. Installs all remaining dependencies from requirements-desktop.txt
rem
rem  Re-runnable: every step skips work that is already done,
rem  so you can simply run this script again after a failure.
rem
rem  After setup, start the service with:
rem     RADAR_inference\deploy\start_server.bat
rem ============================================================

set "VENV=%CD%\RADAR_inference\env"
set "REQ=%CD%\requirements-desktop.txt"
set "TORCH_VERSION=2.8.0"
set "TORCHVISION_VERSION=0.23.0"
set "TORCHAUDIO_VERSION=2.8.0"

rem ---- Locate the interpreter inside %VENV%.
rem      Two layouts exist in the wild:
rem        Scripts\python.exe - standard venv (python -m venv), and the layout
rem                            setup_env.bat itself creates on Windows
rem        python.exe        - conda / conda-pack, which drops the interpreter
rem                            at the env root instead of in Scripts\
rem      start_server.bat probes both, so setup must accept both too.
set "_PYV_PREV="
if exist "%VENV%\Scripts\python.exe" set "_PYV_PREV=%VENV%\Scripts\python.exe"
if not defined _PYV_PREV if exist "%VENV%\python.exe" set "_PYV_PREV=%VENV%\python.exe"
set "PYV=%_PYV_PREV%"

echo ============================================================
echo   RadarScope - Environment Setup
echo ============================================================
echo   Target venv : %VENV%
echo   Requires    : Python 3.10.x (3.10.18 is the tested version)
echo.

rem ---- sanity: path with spaces breaks start_server.bat ----
echo "%CD%"| findstr /C:" " >nul
if not errorlevel 1 (
    echo   [WARN] This folder path contains spaces.
    echo   start_server.bat does not support spaces in its launch line.
    echo   If startup fails, move this package to a path without spaces.
    echo.
)

rem ============================================================
rem  STEP 1/5 - virtual environment
rem ============================================================
set "PYV="
if defined _PYV_PREV (
    echo [STEP 1/5] Virtual environment already exists - reusing it.
    set "PYV=%_PYV_PREV%"
    goto :venv_ok
)

echo [STEP 1/5] Creating virtual environment...
set /a PYTRIES=0
call :select_python || goto :fail
echo   Using Python: "%SELECTED%"
"%SELECTED%" -m venv "%VENV%"
if errorlevel 1 (
    echo   [ERROR] Failed to create the virtual environment.
    goto :fail
)
if exist "%VENV%\Scripts\python.exe" set "PYV=%VENV%\Scripts\python.exe"
if not defined PYV if exist "%VENV%\python.exe" set "PYV=%VENV%\python.exe"
if not defined PYV (
    echo   [ERROR] venv was created but no interpreter was found inside it.
    echo           Expected Scripts\python.exe or python.exe under:
    echo           %VENV%
    goto :fail
)

:venv_ok
"%PYV%" -c "import sys; print('   venv python :', sys.version.split()[0], '-', sys.executable)" || goto :fail

rem ============================================================
rem  STEP 2/5 - PyPI mirror
rem ============================================================
set "MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
echo.
echo [STEP 2/5] Choose a PyPI mirror:
echo     1. Tsinghua   https://pypi.tuna.tsinghua.edu.cn/simple    (default)
echo     2. Aliyun     https://mirrors.aliyun.com/pypi/simple
echo     3. Tencent    https://mirrors.cloud.tencent.com/pypi/simple
echo     4. Official   https://pypi.org/simple
set "CH="
set /p "CH=Pick a mirror [1-4], Enter=1: "
if "%CH%"=="2" set "MIRROR=https://mirrors.aliyun.com/pypi/simple"
if "%CH%"=="3" set "MIRROR=https://mirrors.cloud.tencent.com/pypi/simple"
if "%CH%"=="4" set "MIRROR=https://pypi.org/simple"
echo   Mirror: %MIRROR%

rem ============================================================
rem  STEP 3/5 - pip bootstrap
rem ============================================================
echo.
echo [STEP 3/5] Upgrading pip (skipped automatically if already current)...
"%PYV%" -m pip install --upgrade pip -i "%MIRROR%" --quiet
if errorlevel 1 echo   [WARN] pip upgrade failed - continuing with the bundled pip.

rem ============================================================
rem  STEP 4/5 - PyTorch (skipped if already importable)
rem ============================================================
echo.
echo [STEP 4/5] PyTorch
"%PYV%" -c "import torch" >nul 2>&1
if not errorlevel 1 goto :torch_present

set "TORCH_INDEX=https://download.pytorch.org/whl/cpu"
set "TORCH_DEFAULT=CPU"
where nvidia-smi >nul 2>&1
if not errorlevel 1 (
    set "TORCH_DEFAULT=GPU"
    echo   NVIDIA GPU detected: nvidia-smi found.
) else (
    echo   No NVIDIA GPU detected (nvidia-smi not found).
)
echo     1. GPU build  - CUDA 12.9 wheels, ~2.5 GB download (for NVIDIA GPUs)
echo     2. CPU build  - smaller download, slower inference
set "CH="
set /p "CH=Pick torch build [1/2], Enter=%TORCH_DEFAULT%: "
if "%CH%"=="1" set "TORCH_INDEX=https://download.pytorch.org/whl/cu129"
if "%CH%"=="2" set "TORCH_INDEX=https://download.pytorch.org/whl/cpu"
if not "%CH%"=="1" if not "%CH%"=="2" (
    if "%TORCH_DEFAULT%"=="GPU" set "TORCH_INDEX=https://download.pytorch.org/whl/cu129"
)
echo   Wheel index: %TORCH_INDEX%
echo   (torch download can take a while depending on your connection)
set /a TRY=1
:torch_install
"%PYV%" -m pip install torch==%TORCH_VERSION% torchvision==%TORCHVISION_VERSION% torchaudio==%TORCHAUDIO_VERSION% --index-url "%TORCH_INDEX%" --retries 5 --timeout 60 && goto :torch_ok
if %TRY% geq 3 (
    echo   [ERROR] torch installation failed after 3 attempts.
    echo   Re-run this script to resume; already-installed parts are skipped.
    goto :fail
)
set /a TRY+=1
echo   [RETRY] torch install failed - attempt !TRY! of 3...
goto :torch_install

:torch_present
"%PYV%" -c "import torch; print('   [SKIP] torch', torch.__version__, 'already installed | CUDA available:', torch.cuda.is_available())"
goto :torch_done
:torch_ok
echo   torch installed.
:torch_done

rem ============================================================
rem  STEP 5/5 - all remaining dependencies
rem  (pip skips every requirement it already satisfies -> resumable)
rem ============================================================
echo.
echo [STEP 5/5] Installing dependencies (already-installed ones are skipped)...
set /a TRY=1
:req_install
"%PYV%" -m pip install -r "%REQ%" -i "%MIRROR%" --retries 5 --timeout 60 && goto :req_ok
if %TRY% geq 3 (
    echo   [ERROR] Dependency installation failed after 3 attempts.
    echo   Re-run this script to resume; it skips everything already installed.
    goto :fail
)
set /a TRY+=1
echo   [RETRY] dependency install failed - attempt !TRY! of 3...
goto :req_install
:req_ok
echo   Dependencies installed.

rem ============================================================
rem  Verify
rem ============================================================
echo.
echo [VERIFY] Importing core packages...
"%PYV%" -c "import torch, torchvision, fastapi, uvicorn, monai, transformers, timm, nibabel, SimpleITK, numpy, pandas, cv2; print('   torch', torch.__version__, '| CUDA available:', torch.cuda.is_available()); print('   ALL CORE PACKAGES OK')"
if errorlevel 1 (
    echo   [ERROR] Verification failed - re-run this script to repair.
    goto :fail
)
if defined TORCH_INDEX if "%TORCH_INDEX%"=="https://download.pytorch.org/whl/cpu" (
    echo   [NOTE] CPU-only torch installed. Inference works but is slower;
    echo   re-run this script and pick the GPU build if an NVIDIA GPU is available.
)
echo.
echo ============================================================
echo   Checking model weights...
echo ============================================================
set "NEED_DL="
if exist "ckpt\checkpoint_radar_pretrain.pth" (
    echo   main weights         : OK
) else (
    echo   [NOTE] main weights missing: ckpt\checkpoint_radar_pretrain.pth
    set "NEED_DL=1"
)
if exist "ckpt\bert-base-chinese\config.json" (
    echo   main bert-base-chinese: OK
) else (
    echo   [NOTE] bert-base-chinese missing - required by main.
    set "NEED_DL=1"
)
if exist "ckpt\infer_text_embedding_radar.pt" (
    echo   main text embedding  : OK
) else (
    echo   [ERROR] infer_text_embedding_radar.pt missing - restore it from the package.
)

rem 注意：set /p 必须处于顶层，放在括号块内会读不到输入（cmd 已知行为）
if defined NEED_DL goto :ask_download
goto :after_download

:ask_download
echo.
echo   Model weights are required. Download now from the official repo?
echo   ^(via hf-mirror.com, resumable - just re-run if interrupted^)
echo     1^) main only   ^(~1.9 GB^)
echo     2^) main + plus ^(~3.5 GB, plus has the higher AUC^)
echo     3^) skip for now
set "DLCH=3"
set /p "DLCH=  Choice [1/2/3]: "
if "!DLCH!"=="1" (
    "%PYV%" RADAR_inference\scripts\download_weights.py --preset main
    if errorlevel 1 echo   [WARN] Download failed - re-run this script to retry.
    goto :after_download
)
if "!DLCH!"=="2" (
    "%PYV%" RADAR_inference\scripts\download_weights.py --preset all
    if errorlevel 1 echo   [WARN] Download failed - re-run this script to retry.
    goto :after_download
)
echo   Skipped. Download later with:
echo     "%PYV%" RADAR_inference\scripts\download_weights.py --preset main
echo   or from the admin page ^(Model weights^) after starting the service.
goto :after_download

:after_download

if exist "ckpt\checkpoint_radar_plus_finetuned_on_merlin.pth" (
    echo   plus weights         : OK
) else (
    echo   [NOTE] plus weights not found ^(optional^) - main works standalone.
)
if exist "ckpt\infer_text_embedding_merlin_en.pt" (
    echo   plus text embedding  : OK
) else if exist "ckpt\checkpoint_radar_plus_finetuned_on_merlin.pth" (
    echo   Generating plus text embedding from official MERLIN prompts...
    pushd RADAR_inference
    "%PYV%" -m radar.engine.text_embed --items merlin20 --checkpoint ..\ckpt\checkpoint_radar_plus_finetuned_on_merlin.pth
    popd
    if errorlevel 1 (
        echo   [WARN] Generation failed. Re-run later with:
        echo          cd RADAR_inference ^&^& python -m radar.engine.text_embed --items merlin20
    )
)

echo.
echo ============================================================
echo   Setup finished.
echo.
echo   venv     : %VENV%
echo   Start    : RADAR_inference\deploy\start_server.bat
echo              (LAN)   start_server.bat
echo              (local) start_server.bat local
echo.
echo   First run loads model weights, taking ~10-30s; then open
echo   http://127.0.0.1:8125/ in your browser.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo   [ERROR] Setup did not finish. Fix the problem shown above and
echo   run setup_env.bat again - finished steps are skipped automatically.
pause
exit /b 1

rem ============================================================
rem  Subroutine: pick a Python 3.10 interpreter interactively
rem  Sets SELECTED on success.
rem ============================================================
:select_python
set /a PYTRIES+=1
if %PYTRIES% gtr 5 (
    echo   [ERROR] Too many invalid selections.
    exit /b 2
)
echo.
echo   Scanning for Python 3.10 installations...
set "CFILE=%TEMP%\radar_py_candidates.txt"
type nul > "%CFILE%"

rem -- py launcher (python.org installs)
py -3.10 -c "import sys; print(sys.executable)" > "%TEMP%\radar_py310.txt" 2>nul
if not errorlevel 1 for /f "usebackq delims=" %%p in ("%TEMP%\radar_py310.txt") do >>"%CFILE%" echo %%p

rem -- python on PATH
for /f "delims=" %%p in ('where python 2^>nul') do >>"%CFILE%" echo %%p

rem -- common install locations
for %%p in (
    "C:\Python310\python.exe"
    "C:\Program Files\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\anaconda3\python.exe"
    "%USERPROFILE%\anaconda3\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
    "C:\ProgramData\miniconda3\python.exe"
    "C:\miniconda3\python.exe"
) do if exist "%%~p" >>"%CFILE%" echo %%~p

set "N=0"
for /f "usebackq delims=" %%p in ("%CFILE%") do (
    set /a N+=1
    set "CAND_!N!=%%p"
)
if %N% gtr 0 (
    echo.
    echo   Found candidates:
    for /l %%i in (1,1,%N%) do call :show_cand %%i
) else (
    echo   No Python found automatically.
)

echo.
set "CH="
set /p "CH=Select [1-%N%], Enter for manual input, or paste a full python.exe path: "
set "SELECTED="
if "%CH%"=="" goto :manual_py
echo %CH%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 (
    set "SELECTED=%CH:"=%"
) else (
    if %CH% leq %N% call :get_cand %CH%
)
if defined SELECTED goto :validate_sel

:manual_py
set "CH="
set /p "CH=Full path to python.exe: "
if not defined CH goto :select_python
set "SELECTED=%CH:"=%"

:validate_sel
"%SELECTED%" -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    echo   [SKIP] Not a working Python 3.10: "%SELECTED%"
    goto :select_python
)
for /f "delims=" %%v in ('"%SELECTED%" -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%v"
echo   Selected: "%SELECTED%"  (Python %PYVER%)
exit /b 0

:show_cand
echo     %1. !CAND_%1!
exit /b 0

:get_cand
set "SELECTED=!CAND_%1!"
exit /b 0
