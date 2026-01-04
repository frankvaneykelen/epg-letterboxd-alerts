"""
Azure Functions application setup.
This file is used when deploying to Azure Functions.
"""

import azure.functions as func
from __init__ import main
from pathlib import Path

app = func.FunctionApp()


@app.timer_trigger(arg_name="mytimer", schedule="0 */6 * * * *")  # Every 6 hours
def epg_letterboxd_alerts_timer(mytimer: func.TimerRequest) -> None:
    """
    TimerTrigger function for EPG-Letterboxd Alerts.
    Runs every 6 hours (configurable via cron expression).
    """
    main(mytimer)


@app.route(route="", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def index(req: func.HttpRequest) -> func.HttpResponse:
    """Serve the films index.html page"""
    html_path = Path("wwwroot/index.html")
    if html_path.exists():
        return func.HttpResponse(
            html_path.read_text(encoding='utf-8'),
            mimetype="text/html",
            status_code=200
        )
    return func.HttpResponse("No films data available yet. Function needs to run first.", status_code=404)


@app.route(route="new-series", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def new_series(req: func.HttpRequest) -> func.HttpResponse:
    """Serve the new-series.html page"""
    html_path = Path("wwwroot/new-series.html")
    if html_path.exists():
        return func.HttpResponse(
            html_path.read_text(encoding='utf-8'),
            mimetype="text/html",
            status_code=200
        )
    return func.HttpResponse("No series data available yet. Function needs to run first.", status_code=404)

