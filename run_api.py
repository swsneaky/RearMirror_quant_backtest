"""
RearMirror API 启动脚本

用法:
    python run_api.py
    python run_api.py --port 8080
    python run_api.py --host 0.0.0.0 --port 8000
"""
import argparse
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="启动 RearMirror API 服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="监听端口 (默认: 8000)")
    parser.add_argument("--reload", action="store_true", help="开发模式 (自动重载)")
    args = parser.parse_args()

    print(f"Starting RearMirror API on {args.host}:{args.port}")
    print(f"API docs: http://{args.host}:{args.port}/docs")

    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
