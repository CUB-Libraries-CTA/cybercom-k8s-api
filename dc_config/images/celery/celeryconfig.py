import os
import ssl

# CUBL: Enable logging
import sys
import logging
from celery.signals import after_setup_logger

# Refer to Celery's configuration documentation for details on these settings.
# https://docs.celeryproject.org/en/stable/userguide/configuration.html

def setBrokerSSL():
    if os.environ.get('BROKER_USE_SSL'):
        return {'keyfile': '/ssl/client/key.pem',
                'certfile': '/ssl/client/cert.pem',
                'ca_certs': '/ssl/testca/cacert.pem',
                'cert_reqs': ssl.CERT_REQUIRED}
    else:
        return None

# SETUP BROOKER URI
RABBITMQ_DEFAULT_USER = os.environ.get('RABBITMQ_DEFAULT_USER')
RABBITMQ_DEFAULT_PASS = os.environ.get('RABBITMQ_DEFAULT_PASS')
RABBITMQ_DEFAULT_VHOST = os.environ.get('RABBITMQ_DEFAULT_VHOST')
broker_url = f"amqp://{RABBITMQ_DEFAULT_USER}:{RABBITMQ_DEFAULT_PASS}@cybercom-rabbitmq:5671/{RABBITMQ_DEFAULT_VHOST}"
broker_use_ssl = setBrokerSSL()
worker_send_task_events = True
result_expires = None
accept_content = ['json']

# SETUP MONGO URI
SSL_PATH = os.environ.get('SSL_PATH')
MONGO_USERNAME = os.environ.get('MONGO_USERNAME')
MONGO_PASSWORD = os.environ.get('MONGO_PASSWORD')
result_backend = f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@cybercom-mongo:27017/?ssl=true&ssl_ca_certs={SSL_PATH}/testca/cacert.pem&ssl_certfile={SSL_PATH}/client/mongodb.pem"

mongodb_backend_settings = {
    "database": os.environ.get('MONGO_DB', "cybercom"),
    "taskmeta_collection": os.environ.get('MONGO_TOMBSTONE_COLLECTION', "tombstone")
}

imports = tuple(os.environ.get('CELERY_IMPORTS').split(','))


@after_setup_logger.connect
def setup_loggers(logger, *args, **kwargs):
    logger.addHandler(logging.StreamHandler(sys.stdout))
