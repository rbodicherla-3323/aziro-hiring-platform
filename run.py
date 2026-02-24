import argparse
import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-debug", action="store_true",
                        help="Disable debug/reloader (use in production)")
    args = parser.parse_args()

    # Production: pass --no-debug OR set FLASK_DEBUG=0 in environment
    debug = not args.no_debug and os.getenv("FLASK_DEBUG", "1") != "0"
    app.run(host=args.host, port=args.port, debug=debug)
