import argparse
import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug/reloader (development only)",
    )
    parser.add_argument("--no-debug", action="store_true",
                        help="Disable debug/reloader (use in production)")
    args = parser.parse_args()

    # Default to production-safe mode (debug off). Enable only with --debug
    # or FLASK_DEBUG=1/true/yes/on, unless --no-debug is passed.
    debug_env = os.getenv("FLASK_DEBUG", "").strip().lower()
    debug_from_env = debug_env in {"1", "true", "yes", "on"}
    debug = (args.debug or debug_from_env) and not args.no_debug
    app.run(host=args.host, port=args.port, debug=debug)
