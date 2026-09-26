#!/bin/bash
# Zamanlanmış tetikleyici: panodan TEK bir hazır görevi yürütür.
#
# Tasarım: her tetiklemede tek görev alınır ve pano yeniden değerlendirilir.
# Böylece "sprint uzarsa sonraki başlamasın" kuralı zamanlayıcıya değil
# durum makinesine bağlı kalır — cron sadece dürter, karar vermez.
cd "$(dirname "$0")" || exit 1
mkdir -p workspace/logs
exec .venv/bin/python studio_engine.py --tick >> workspace/logs/pipeline.log 2>&1
