"""Safe errors for the UI; never include provider payloads or credentials."""


class AppError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}
