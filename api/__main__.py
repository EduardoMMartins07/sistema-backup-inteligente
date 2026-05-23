import uvicorn

from api.config import get_settings


def main():
    settings = get_settings()
    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=settings.port,
        reload=settings.environment == "development",
    )


if __name__ == "__main__":
    main()
