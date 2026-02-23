# ChatGPT used for troubleshooting, suggestions and generating
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
import os
from dotenv import load_dotenv

db = SQLAlchemy()

# DB setup and maintenance - Lumary YT https://www.youtube.com/watch?v=XZ_gAWdGzZk, Postegresql.org
# https://www.postgresql.org/docs/current/libpq-envars.html, https://www.youtube.com/shorts/RctRuV8hObw maintenance -
# ChatGPT maintenance of database - See documentation for conversation
def create_app():
    load_dotenv()
    app = Flask(__name__, template_folder="templates")
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app) # connects SQLAlchemy to Flask app

    # Importing models & bp so SQLAlchemy knows the tables, unused import problem https://stackoverflow.com/questions/
    # 11957106/unused-import-warning-and-pylint
    from models import Product  # noqa: F401
    from views import bp as main_bp
    app.register_blueprint(main_bp) # calls all models using one line https://flask.palletsprojects.com/en/stable/

    # create tables if they don't exist
    with app.app_context():
        db.create_all()

# directs you to index page
    @app.route("/")
    def index():
        return redirect(url_for("main.products"))

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
