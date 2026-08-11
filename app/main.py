# Main application module
from fastapi import FastAPI

app = FastAPI(title="Multi-Channel Notification Delivery System")

@app.get("/health")
def health_check():
    return {"status": "ok"}