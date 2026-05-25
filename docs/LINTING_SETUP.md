# Настройка линтеров AI Judge

## Быстрый старт (5 минут)

```bash
# 1. Установить dev-зависимости
pip install -r requirements-dev.txt

# 2. Проверить код
ruff check app/                 # линтинг (security, bugs, style)
ruff format --check app/        # проверка форматирования
mypy app/                       # типизация (ловит None-баги)

# 3. Автоисправление
ruff check --fix app/           # автофикс простых ошибок
ruff format app/                # автоформатирование

# 4. Или всё сразу
chmod +x lint.sh
./lint.sh          # проверить
./lint.sh --fix    # проверить + исправить
```

## Pre-commit — автоматика при каждом коммите

```bash
pip install pre-commit
pre-commit install

# Теперь при каждом git commit автоматически:
# ✅ ruff проверит и поправит стиль
# ✅ ruff проверит security (SQL injection, hardcoded secrets)
# ✅ mypy проверит типы (None на nullable колонках)
# ✅ detect-private-key ловит случайные ключи
# ✅ hadolint проверит Dockerfile
# ❌ не даст коммитить в main напрямую
```

## Что ловит каждый инструмент

### Ruff (замена flake8 + isort + black + bandit)
- `S` (bandit): SQL injection, eval(), hardcoded secrets, pickle
- `ASYNC`: забытый await, blocking calls в async функциях
- `DTZ`: datetime.now() без timezone
- `B` (bugbear): mutable default arguments, except Exception: pass
- `T20`: print() в продакшн-коде
- `F`: неиспользуемые импорты, undefined переменные

### Mypy (статическая типизация)
- None на nullable колонках (Column без nullable=False)
- Неправильные типы аргументов
- Недостижимый код
- Несовместимые return types

### pip-audit (безопасность зависимостей)
- Известные уязвимости (CVE) в requirements.txt

## Рекомендации по ГОСТ Р 56939-2024

Для подготовки к сертификации ФСТЭК:
1. Результаты ruff + mypy = артефакты статического анализа
2. Git history + pre-commit = управление конфигурациями
3. CI/CD pipeline = автоматизация контроля качества
4. pip-audit = управление уязвимостями зависимостей
