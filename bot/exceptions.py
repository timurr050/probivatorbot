"""Типизированные исключения для всех уровней бота."""


class ProbivError(Exception):
    """Базовая ошибка бота."""


class ConfigError(ProbivError):
    """Ошибка конфигурации (не задан токен, API ключ и т.п.)."""


class ValidationError(ProbivError):
    """Пользователь прислал данные в неправильном формате.

    Атрибут `expected` — человекочитаемое описание ожидаемого формата,
    которое будет показано пользователю.
    """

    def __init__(self, message: str, expected: str = ""):
        super().__init__(message)
        self.message = message
        self.expected = expected


class ServiceError(ProbivError):
    """Внутренняя ошибка сервиса OSINT (сеть, таймаут, парсинг)."""


class ToolNotConfigured(ServiceError):
    """Инструмент доступен, но не настроен (нет бинарника/API ключа)."""


class ToolTimeout(ServiceError):
    """Инструмент не уложился в таймаут."""


class ExternalToolError(ServiceError):
    """CLI-инструмент упал с ненулевым кодом / мусорным выводом."""