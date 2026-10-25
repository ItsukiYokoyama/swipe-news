# Build the Windows release: a zip with Python bundled that runs by double-clicking. No custom exe is built
#   powershell -ExecutionPolicy Bypass -File packaging\build-portable.ps1 [-ModelDir models\ruri-v3-30m] [-OutDir dist]
# Contents: the python.org embeddable Python (signed by the Python Software Foundation) + libraries + app + model + extension.
# Users just extract the zip and double-click "Swipe News.cmd" (no uv or Python needed). uv is used only for building
param(
  [string]$ModelDir = "",
  [string]$OutDir = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $ModelDir) { $ModelDir = Join-Path $root "models\ruri-v3-30m" }
if (-not $OutDir) { $OutDir = Join-Path $root "dist" }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  throw "uv is required. Install it first: winget install --id=astral-sh.uv -e"
}

# Pin the Python version and hash (python.org doesn't publish hashes; this one was taken after verifying the signature)
$PyVersion = "3.12.10"
$PyUrl = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-embed-amd64.zip"
$PySha256 = "4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3"

$appVersion = (Select-String -Path (Join-Path $root "pyproject.toml") -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
$name = "SwipeNews"
$work = Join-Path $OutDir "build"
$stage = Join-Path $work $name
$py = Join-Path $stage "python"
$site = Join-Path $py "Lib\site-packages"
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force $py | Out-Null

# 1. Embeddable Python
$embedZip = Join-Path $OutDir "python-$PyVersion-embed-amd64.zip"
if (-not (Test-Path $embedZip) -or (Get-FileHash $embedZip).Hash -ne $PySha256) {
  Write-Host "Downloading Python $PyVersion"
  Invoke-WebRequest $PyUrl -OutFile $embedZip -UseBasicParsing
}
if ((Get-FileHash $embedZip).Hash -ne $PySha256) { throw "Hash mismatch for the Python zip" }
Expand-Archive $embedZip $py
foreach ($f in "python.exe", "pythonw.exe", "python312.dll") {
  $sig = Get-AuthenticodeSignature (Join-Path $py $f)
  if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notlike "CN=Python Software Foundation,*") {
    throw "Could not verify the signature of $f ($($sig.Status))"
  }
}
# The embeddable Python ignores site-packages unless listed in ._pth (with ._pth, PYTHONPATH is ignored too, isolating it from other Pythons)
Set-Content -Path (Join-Path $py "python312._pth") -Encoding ascii -Value @(
  "python312.zip", ".", "Lib\site-packages", "import site"
)

# 2. Libraries and the app, with precompiled .pyc (faster startup). .pyc files are version-specific, so build them with the same 3.12
uv pip install --target $site --python 3.12 --python-platform x86_64-pc-windows-msvc `
  --compile-bytecode "$root[desktop]"
if ($LASTEXITCODE -ne 0) { throw "uv pip install failed" }
Remove-Item -Recurse -Force (Join-Path $site "bin") -ErrorAction SilentlyContinue

# 3. Model (genre_ai doesn't download it when it's present in swipe_news/models/)
$modelDest = Join-Path $site "swipe_news\models\ruri-v3-30m"
New-Item -ItemType Directory -Force $modelDest | Out-Null
Copy-Item (Join-Path $ModelDir "model_int8.onnx"), (Join-Path $ModelDir "tokenizer.json") $modelDest

# 4. Launcher cmd, extension and docs. The cmd window closes at once, leaving pythonw (no console) running
Set-Content -Path (Join-Path $stage "Swipe News.cmd") -Encoding ascii -Value @(
  "@echo off", 'start "" "%~dp0python\pythonw.exe" -m swipe_news %*'
)
Copy-Item -Recurse (Join-Path $root "extension") (Join-Path $stage "extension")
Copy-Item (Join-Path $root "LICENSE"), (Join-Path $root "THIRD_PARTY_NOTICES.md"), (Join-Path $root "README.md") $stage
Set-Content -Path (Join-Path $py "swipe-news-portable") -Encoding ascii -Value $appVersion
$readme = @"
Swipe News $appVersion (Windows 版)

起動: 「Swipe News.cmd」をダブルクリック。ブラウザが開き、タスクトレイにアイコンが出ます。
      初回に、スタートメニューへ「Swipe News」を登録します (このフォルダを動かしたら、もう一度 cmd から起動してください)。
終了: タスクトレイのアイコンを右クリック →「終了」。
データ: %LOCALAPPDATA%\SwipeNews (操作の記録・学習・設定・メディアの一覧)。このフォルダとは別なので、入れ替えても残ります。
消す: このフォルダと、スタートメニューの「Swipe News」を消す。データも消すなら %LOCALAPPDATA%\SwipeNews も。

ダウンロードした zip は、展開する前に右クリック →「プロパティ」→「許可する」にチェックを入れてください
(しないと、最初の起動で「発行元を確認できませんでした」と出ます。「実行」を押せば、次からは出ません)。

個人で読む目的に限って使ってください。メディアを追加する前に、そのメディアの利用規約を読んで、内容を守ってください。

Chrome 拡張機能「十字キーで戻る」は extension フォルダ。入れ方は README.md を見てください。
ライセンス: GPL-3.0-or-later (LICENSE)。同梱しているソフトウェアのライセンスは THIRD_PARTY_NOTICES.md と python\LICENSE.txt。
"@
[IO.File]::WriteAllText((Join-Path $stage "はじめに.txt"), $readme, (New-Object Text.UTF8Encoding $true))

# 5. Zip it (Windows' built-in tar; Git's GNU tar can't create zips, so use the full path)
$zip = Join-Path $OutDir "$name-$appVersion-windows.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
& "$env:SystemRoot\System32\tar.exe" -a -c -f $zip -C $work $name
if ($LASTEXITCODE -ne 0) { throw "Could not create the zip" }
Write-Host ("Created: {0} ({1:N0} MB)" -f $zip, ((Get-Item $zip).Length / 1MB))
