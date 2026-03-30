#!/bin/bash
# HFT System 初始化脚本
# 配置环境 + 构建 Go 引擎 + 部署 pre-commit 钩子

set -e  # 脚本出错立即退出

echo "========================================"
echo "    HFT System 项目初始化"
echo "========================================"

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. 赋予自身可执行权限
chmod +x "$0" 2>/dev/null || true

# 2. 安装 Go 依赖
echo -e "\n[1/5] 安装 Go 依赖..."
if [ -d "core_go" ]; then
    cd core_go
    if command -v go &> /dev/null; then
        go mod tidy
        echo "✅ Go 依赖安装完成"
    else
        echo "⚠️  Go 未安装，跳过 Go 依赖安装"
    fi
    cd ..
else
    echo "⚠️  未找到 core_go 目录"
fi

# 3. 安装 Python 依赖
echo -e "\n[2/5] 安装 Python 依赖..."
if [ -f "brain_py/requirements.txt" ]; then
    pip install -r brain_py/requirements.txt -q
    echo "✅ Python 依赖安装完成 (brain_py)"
else
    echo "⚠️  未找到 brain_py/requirements.txt"
fi

# 如果存在项目级 requirements.txt
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt -q
    echo "✅ Python 依赖安装完成 (项目级)"
fi

# 4. 构建 Go 引擎
echo -e "\n[3/5] 构建 Go HFT 引擎..."
if [ -d "core_go" ] && command -v go &> /dev/null; then
    cd core_go
    go build -o hft_engine.exe . 2>/dev/null || go build -o hft_engine .
    if [ -f "hft_engine.exe" ] || [ -f "hft_engine" ]; then
        echo "✅ Go 引擎构建成功"
    else
        echo "❌ Go 引擎构建失败"
        exit 1
    fi
    cd ..
else
    echo "⚠️  跳过 Go 引擎构建"
fi

# 5. 部署 pre-commit 钩子
echo -e "\n[4/5] 部署 Git pre-commit 钩子..."
if [ -d ".git" ]; then
    # 创建 hooks 目录（如果不存在）
    mkdir -p .git/hooks

    # 写入 pre-commit 钩子
    cat > .git/hooks/pre-commit << 'EOF'
#!/bin/bash
# HFT System Pre-commit 钩子
# 提交前自动运行系统测试

set -e

echo "========================================"
echo "    HFT System 提交前检查"
echo "========================================"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 获取项目根目录
PROJECT_ROOT="$(git rev-parse --show-toplevel)"
cd "$PROJECT_ROOT"

# 1. 运行系统测试（最轻量级）
echo -e "\n[1/3] 运行系统测试 (test_system.py)..."
if [ -f "test_system.py" ]; then
    if python test_system.py; then
        echo -e "${GREEN}✅ 系统测试通过${NC}"
    else
        echo -e "${RED}❌ 系统测试失败${NC}"
        echo "请修复测试后重新提交"
        exit 1
    fi
else
    echo -e "${YELLOW}⚠️  未找到 test_system.py，跳过${NC}"
fi

# 2. 检查 Go 代码格式（如果有修改）
echo -e "\n[2/3] 检查 Go 代码格式..."
if command -v gofmt &> /dev/null; then
    GO_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\.go$' || true)
    if [ -n "$GO_FILES" ]; then
        UNFORMATTED=$(gofmt -l $GO_FILES 2>/dev/null || true)
        if [ -n "$UNFORMATTED" ]; then
            echo -e "${RED}❌ 以下 Go 文件需要格式化:${NC}"
            echo "$UNFORMATTED"
            echo "运行: gofmt -w $UNFORMATTED"
            exit 1
        else
            echo -e "${GREEN}✅ Go 代码格式正确${NC}"
        fi
    else
        echo "ℹ️  没有 Go 文件修改，跳过"
    fi
else
    echo -e "${YELLOW}⚠️  gofmt 未安装，跳过${NC}"
fi

# 3. 检查核心文件语法
echo -e "\n[3/3] 检查 Python 语法..."
PY_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' || true)
if [ -n "$PY_FILES" ]; then
    SYNTAX_ERRORS=0
    for file in $PY_FILES; do
        if [ -f "$file" ]; then
            if ! python -m py_compile "$file" 2>/dev/null; then
                echo -e "${RED}❌ 语法错误: $file${NC}"
                SYNTAX_ERRORS=$((SYNTAX_ERRORS + 1))
            fi
        fi
    done

    if [ $SYNTAX_ERRORS -eq 0 ]; then
        echo -e "${GREEN}✅ Python 语法检查通过${NC}"
    else
        echo -e "${RED}❌ 发现 $SYNTAX_ERRORS 个语法错误${NC}"
        exit 1
    fi
else
    echo "ℹ️  没有 Python 文件修改，跳过"
fi

echo -e "\n========================================"
echo -e "${GREEN}✅ 所有检查通过，允许提交${NC}"
echo "========================================"
exit 0
EOF

    # 赋予执行权限
    chmod +x .git/hooks/pre-commit
    echo "✅ pre-commit 钩子部署完成"
else
    echo "⚠️  未找到 .git 目录，跳过钩子部署"
    echo "提示: 请先运行 git init 初始化仓库"
fi

# 6. 创建必要的目录
echo -e "\n[5/5] 创建项目目录..."
mkdir -p data logs checkpoints
echo "✅ 目录创建完成"

# 7. 完成提示
echo -e "\n========================================"
echo -e "🎉 ${GREEN}HFT System 初始化完成！${NC}"
echo "========================================"
echo -e "\n可用命令:"
echo "  构建引擎:   cd core_go && go build -o hft_engine.exe ."
echo "  运行测试:   python test_system.py"
echo "  运行 E2E:   python end_to_end_test.py"
echo "  启动引擎:   cd core_go && ./hft_engine.exe btcusdt"
echo "  启动Agent:  cd brain_py && python agent.py"
echo -e "\n现在开始开发吧！"
