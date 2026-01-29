import logging

from flask import Flask, flash, redirect, render_template, request, url_for

from .database import Database

logger = logging.getLogger(__name__)


def create_app(database: Database) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.secret_key = "price-checker-secret"

    @app.route("/")
    def index():
        products = database.get_all_products()
        return render_template("index.html", products=products)

    @app.route("/add", methods=["GET"])
    def add_form():
        return render_template("add.html")

    @app.route("/add", methods=["POST"])
    def add_product():
        url = request.form.get("url", "").strip()
        name = request.form.get("name", "").strip() or None

        if not url:
            flash("URL is required.", "error")
            return redirect(url_for("add_form"))

        product = database.add_product(url, name)
        flash(f"Product '{product.name or product.url}' added.", "success")
        return redirect(url_for("index"))

    @app.route("/product/<int:product_id>")
    def product_detail(product_id: int):
        product = database.get_product_by_id(product_id)
        if product is None:
            flash("Product not found.", "error")
            return redirect(url_for("index"))

        history = database.get_product_history(product_id)
        return render_template("product.html", product=product, history=history)

    return app
