"""
Azure Functions application setup.
This file is used when deploying to Azure Functions.
"""

import azure.functions as func
# Lazy import to avoid loading all dependencies at module level
# from epg_letterboxd_main import main
# from list_new_series import list_non_films
from pathlib import Path
from blob_html_writer import download_html_from_blob

app = func.FunctionApp()


@app.timer_trigger(arg_name="films_timer", schedule="0 0 */6 * * *")  # Every 6 hours at :00
def epg_letterboxd_movies_timer(films_timer: func.TimerRequest) -> None:
    """
    TimerTrigger function for EPG-Letterboxd Films Alerts.
    Runs every 6 hours at :00 (0:00, 6:00, 12:00, 18:00).
    """
    # Lazy import to avoid module-level dependency loading
    from epg_letterboxd_main import main
    main(films_timer)


@app.timer_trigger(arg_name="series_timer", schedule="0 0 1,7,13,19 * * *")  # 1 hour after films
def epg_letterboxd_series_timer(series_timer: func.TimerRequest) -> None:
    """
    TimerTrigger function for EPG-Letterboxd Series Alerts.
    Runs 1 hour after films timer (1:00, 7:00, 13:00, 19:00).
    """
    # Lazy import to avoid module-level dependency loading
    from list_new_series import list_non_films
    list_non_films()


@app.timer_trigger(arg_name="streaming_timer", schedule="0 17 2 * * 0")  # Every Sunday at 2:17 AM
def streaming_movies_timer(streaming_timer: func.TimerRequest) -> None:
    """
    TimerTrigger function for Streaming Movies Catalog.
    Runs every Sunday at 2:17 AM to refresh the streaming catalog.
    """
    # Lazy import to avoid module-level dependency loading
    from list_streaming_movies import generate_streaming_movies_page
    generate_streaming_movies_page()


@app.timer_trigger(arg_name="streaming_series_timer", schedule="0 37 2 * * 0")  # Every Sunday at 2:37 AM
def streaming_series_timer(streaming_series_timer: func.TimerRequest) -> None:
    """
    TimerTrigger function for Streaming Series Catalog.
    Runs every Sunday at 2:37 AM (20 minutes after movies) to refresh the streaming catalog.
    """
    # Lazy import to avoid module-level dependency loading
    from list_streaming_series import generate_streaming_series_page
    generate_streaming_series_page()


@app.route(route="", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def index(req: func.HttpRequest) -> func.HttpResponse:
    """Serve the films index.html page from blob storage"""
    # Try to download from blob storage first ($web container for static website)
    html_content = download_html_from_blob("index.html")  # Uses $web container by default
    
    if html_content:
        return func.HttpResponse(
            html_content,
            mimetype="text/html",
            status_code=200
        )
    
    # Fallback to local file if blob storage unavailable
    html_path = Path("wwwroot/index.html")
    if html_path.exists():
        return func.HttpResponse(
            html_path.read_text(encoding='utf-8'),
            mimetype="text/html",
            status_code=200
        )
    
    return func.HttpResponse(
        "No films data available yet. Function needs to run first.",
        status_code=404
    )


@app.route(route="new-series", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def new_series(req: func.HttpRequest) -> func.HttpResponse:
    """Serve the new-series.html page from blob storage"""
    # Try to download from blob storage first ($web container for static website)
    html_content = download_html_from_blob("new-series.html")  # Uses $web container by default
    
    if html_content:
        return func.HttpResponse(
            html_content,
            mimetype="text/html",
            status_code=200
        )
    
    # Fallback to local file if blob storage unavailable
    html_path = Path("wwwroot/new-series.html")
    if html_path.exists():
        return func.HttpResponse(
            html_path.read_text(encoding='utf-8'),
            mimetype="text/html",
            status_code=200
        )
    
    return func.HttpResponse(
        "No series data available yet. Function needs to run first.",
        status_code=404
    )


@app.route(route="streaming-movies", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def streaming_movies(req: func.HttpRequest) -> func.HttpResponse:
    """Serve the streaming-movies.html page from blob storage"""
    # Try to download from blob storage first ($web container for static website)
    html_content = download_html_from_blob("streaming-movies.html")  # Uses $web container by default
    
    if html_content:
        return func.HttpResponse(
            html_content,
            mimetype="text/html",
            status_code=200
        )
    
    # Fallback to local file if blob storage unavailable
    html_path = Path("wwwroot/streaming-movies.html")
    if html_path.exists():
        return func.HttpResponse(
            html_path.read_text(encoding='utf-8'),
            mimetype="text/html",
            status_code=200
        )
    
    return func.HttpResponse(
        "No streaming movies data available yet. Function needs to run first.",
        status_code=404
    )


@app.route(route="streaming-series", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def streaming_series(req: func.HttpRequest) -> func.HttpResponse:
    """Serve the streaming-series.html page from blob storage"""
    # Try to download from blob storage first ($web container for static website)
    html_content = download_html_from_blob("streaming-series.html")  # Uses $web container by default
    
    if html_content:
        return func.HttpResponse(
            html_content,
            mimetype="text/html",
            status_code=200
        )
    
    # Fallback to local file if blob storage unavailable
    html_path = Path("wwwroot/streaming-series.html")
    if html_path.exists():
        return func.HttpResponse(
            html_path.read_text(encoding='utf-8'),
            mimetype="text/html",
            status_code=200
        )
    
    return func.HttpResponse(
        "No streaming series data available yet. Function needs to run first.",
        status_code=404
    )

