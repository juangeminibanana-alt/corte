"""Un solo proceso dueño de SQLite, el planificador y las renovaciones OAuth."""
import os

bind = '0.0.0.0:' + os.environ.get('PORT', '10000')
workers = 1
worker_class = 'gthread'
threads = 16
timeout = 120
graceful_timeout = 45
preload_app = False
accesslog = '-'
errorlog = '-'
# Excluye query strings: los callbacks contienen códigos de autorización.
access_log_format = '%(h)s %(m)s %(U)s %(s)s %(L)s'
