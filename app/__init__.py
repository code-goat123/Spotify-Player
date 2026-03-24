"""Flask application factory: wires config, blueprints, and static routes."""
from flask import Flask

from app.config import load_config


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
        static_url_path="/static",
    )
    app.config.from_mapping(load_config())

    from app.routes.api import api_bp

    app.register_blueprint(api_bp)

    @app.route("/")
    def index():
        from flask import render_template

        return render_template("index.html")

    return app
