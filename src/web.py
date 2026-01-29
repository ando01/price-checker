import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask, flash, redirect, render_template, request, url_for

from .database import Database

logger = logging.getLogger(__name__)

JOB_ID = "product_check"


def create_app(database: Database, scheduler: BackgroundScheduler) -> Flask:
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

    @app.route("/settings", methods=["GET"])
    def settings():
        saved = database.get_setting("check_interval_minutes")
        job = scheduler.get_job(JOB_ID)
        if saved is not None:
            interval = int(saved)
        elif job and hasattr(job.trigger, "interval"):
            interval = int(job.trigger.interval.total_seconds() // 60)
        else:
            interval = 0
        paused = job is None or job.next_run_time is None
        return render_template(
            "settings.html", interval=interval, paused=paused
        )

    @app.route("/settings", methods=["POST"])
    def update_settings():
        raw = request.form.get("interval", "").strip()
        try:
            interval = int(raw)
            if interval < 0:
                raise ValueError
        except (ValueError, TypeError):
            flash("Interval must be a non-negative integer.", "error")
            return redirect(url_for("settings"))

        database.set_setting("check_interval_minutes", str(interval))

        job = scheduler.get_job(JOB_ID)
        if job is None:
            flash("Scheduler job not found.", "error")
            return redirect(url_for("settings"))

        if interval > 0:
            scheduler.reschedule_job(
                JOB_ID, trigger=IntervalTrigger(minutes=interval)
            )
            scheduler.resume_job(JOB_ID)
            flash(f"Check interval set to {interval} minute(s).", "success")
        else:
            scheduler.pause_job(JOB_ID)
            flash("Scheduled checks disabled.", "success")

        return redirect(url_for("settings"))

    return app
