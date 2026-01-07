"""Minimal test function"""
import azure.functions as func

app = func.FunctionApp()

@app.route(route="test", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def test(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("Hello from test function!", status_code=200)
