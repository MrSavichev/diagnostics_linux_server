# diagnostics_linux_server

Инструмент диагностики сервера Linux Debian. Собирает данные о состоянии системы, сохраняет отчёт в файл и выдаёт **рекомендации по устранению проблем** на основе найденных метрик.

## Файлы

| Файл | Назначение |
|------|-----------|
| `diagnostics.py` | Главный скрипт. Собирает метрики и формирует отчёт |
| `recommendations.py` | Движок рекомендаций. Анализирует метрики, выдаёт приоритизированные действия |

## Что проверяет

### Система
| Категория | Что именно |
|-----------|-----------|
| **ОС / Ядро** | Дистрибутив, версия ядра, аптайм, таймзона |
| **CPU** | Модель, число ядер, load average **vs nproc** (ключевой сигнал перегрузки) |
| **CPU per-core** | Разбивка по ядрам через `mpstat` |
| **Steal%** | Троттлинг на уровне гипервизора (vmstat) |
| **vmstat** | Run queue, context switches, memory pressure |
| **Top процессы** | Топ-15 по CPU |
| **iostat** | Расширенная статистика дисковых операций |
| **RAM / Swap** | Использование памяти и swap |

### Диск — многоуровневый анализ
| Проверка | Зачем |
|----------|-------|
| `df -hT` | Общий обзор, флаг >85% и >95% |
| Inode usage | Диск может быть "полным" без нехватки байт |
| LVM (vgs/lvs) | Можно ли расширить раздел без downtime |
| `/var` breakdown | Первый шаг при заполнении /var |
| `/var/log` breakdown | Типичный источник: journal, atop, docker logs |
| `/var/lib` breakdown | Docker overlay2 часто скрыт здесь |
| `/var/cache` breakdown | apt cache до 1 ГБ+ |
| Файлы >100MB | Быстрый поиск «жирных» файлов |
| Deleted-but-held files | Объясняет расхождение du vs df |

### Docker
| Проверка | Зачем |
|----------|-------|
| `docker ps -a` | Список контейнеров и статус |
| `docker stats` | Живое CPU/RAM/IO по контейнеру |
| `docker system df` | Сколько занимают образы, тома, build cache |
| Container JSON logs | Часто растут без ротации |

### Логи и журналы
- systemd journal disk usage — вакуум при >1ГБ
- atop log size — хранит ежедневные снимки

### Сеть и безопасность
- Сетевые интерфейсы, слушающие порты
- UFW / iptables
- Запущенные и упавшие systemd-сервисы
- Последние входы, auth.log

## Рекомендации

После сбора данных `recommendations.py` автоматически анализирует метрики и выдаёт приоритизированные рекомендации:

| Уровень | Когда |
|---------|-------|
| `CRITICAL` | LA15/vCPU ≥ 1.0, диск ≥ 95%, RAM ≥ 95%, steal% > 10 |
| `WARN` | LA15/vCPU 0.8–1.0, диск 85–95%, journal > 2ГБ, failed-сервисы, deleted-held файлы |
| `INFO` | Советы по Docker cleanup и профилактике |

Каждая рекомендация содержит:
- **Problem** — что именно обнаружено
- **Commands** — готовые команды для устранения

## Требования

- Python 3.6+
- Linux Debian / Ubuntu
- Для полного доступа к логам и LVM рекомендуется `sudo`
- `sysstat` для mpstat/iostat/pidstat: `sudo apt install sysstat`

## Установка

```bash
git clone https://github.com/MrSavichev/diagnostics_linux_server.git
cd diagnostics_linux_server
```

## Использование

```bash
# Обычный запуск
python3 diagnostics.py

# С sudo (открывает доступ к auth.log, lsof, LVM)
sudo python3 diagnostics.py

# Только рекомендации (тест на синтетических метриках)
python3 recommendations.py
```

## Вывод

1. Прогресс проверок в консоль
2. Полный отчёт с метриками
3. Блок рекомендаций (CRITICAL → WARN → INFO)
4. Файл `report_YYYYMMDD_HHMMSS.txt`

## Лицензия

MIT
