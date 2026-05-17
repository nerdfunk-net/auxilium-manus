from os import environ

import uvicorn

if __name__ == "__main__":
    is_development = environ.get("ENV", "development") == "development"

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=is_development,
    )
