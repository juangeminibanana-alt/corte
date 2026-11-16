import os

bind = '0.0.0.0:' + os.environ.get('PORT', '8080')
workers = 2
worker_class = 'gthread'
threads = 8
timeout = 55
graceful_timeout = 10
accesslog = '-'
errorlog = '-'
access_log_format = '%(h)s %(m)s %(U)s %(s)s %(L)s'
