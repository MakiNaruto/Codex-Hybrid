"""Stable configuration errors shared by application boundaries."""


class ConfigError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)
