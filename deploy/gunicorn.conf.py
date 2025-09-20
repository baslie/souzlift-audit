import multiprocessing

bind = "unix:/run/gunicorn/gunicorn.sock"
workers = max(2, multiprocessing.cpu_count() // 2)
worker_class = "gthread"
threads = 2
accesslog = "/var/log/souzlift/gunicorn-access.log"
errorlog = "/var/log/souzlift/gunicorn-error.log"
loglevel = "info"
max_requests = 1000
max_requests_jitter = 100
timeout = 60
graceful_timeout = 30
keepalive = 2
capture_output = True
preload_app = True
chdir = "/opt/souzlift"
pythonpath = ["/opt/souzlift"]
