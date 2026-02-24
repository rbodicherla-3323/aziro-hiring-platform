import argparse
from app import create_app

app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=True)
