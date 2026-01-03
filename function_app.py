"""
Azure Functions application setup.
This file is used when deploying to Azure Functions.
"""

import azure.functions as func
from __init__ import main

app = func.FunctionApp()


@app.timer_trigger(arg_name="mytimer", schedule="0 */6 * * * *")  # Every 6 hours
def epg_letterboxd_alerts(mytimer: func.TimerRequest) -> None:
    """
    TimerTrigger function for EPG-Letterboxd Alerts.
    Runs every 6 hours (configurable via cron expression).
    """
    main(mytimer)
