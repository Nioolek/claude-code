@echo off
echo Starting LiteLLM Proxy...

:: 设置你的 OpenAI API Key
set OPENAI_API_KEY=你的-openai-api-key

:: 启动 LiteLLM Proxy（后台运行）
start "LiteLLM Proxy" cmd /k "litellm --config G:\code\claude-code\litellm_config.yaml"

:: 等待 3 秒让 Proxy 启动
timeout /t 3 /nobreak

:: 设置 Claude Code 连接代理
set ANTHROPIC_API_KEY=sk-1234
set ANTHROPIC_BASE_URL=http://localhost:4000/anthropic

echo.
echo LiteLLM Proxy 已启动！
echo Claude Code 现在可以使用 OpenAI 模型了
echo.
echo 运行 claude 开始使用
echo 按 Ctrl+C 停止 Proxy
