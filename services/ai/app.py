from common import APIError, Handler, serve, validate_text
from services.ai.model import Classifier

MODEL = Classifier()


class AI(Handler):
    def route(self, method, path):
        if method == "GET" and path == "/healthz":
            return self.send(200, {"service": "ai", "status": "ok", "model_version": MODEL.version})
        if method == "POST" and path == "/predict":
            return self.send(200, MODEL.predict(validate_text(self.body())))
        raise APIError(404, "Not found.")


if __name__ == "__main__":
    serve(AI)
