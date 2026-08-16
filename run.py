from truepeak.api import create_app
from truepeak.config import Config

app = create_app()


if __name__ == "__main__":
    cfg = Config()
    from waitress import serve

    serve(app, host=cfg.HOST, port=cfg.PORT)
