FROM python:3.8-alpine3.15
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONUNBUFFERED=1

WORKDIR /
COPY requirements.txt ./
# mysql requirements
# RUN apk add mariadb-dev \
#     gcc \
#     musl-dev \
#     libxml2-dev \
#     libxslt-dev \
#     xmlsec-dev \
#     git \
#     tzdata

RUN apk add build-base libressl libffi-dev libressl-dev libxslt-dev libxml2-dev xmlsec-dev xmlsec
RUN apk add mariadb-dev git tzdata
RUN cp /usr/share/zoneinfo/America/Denver /etc/localtime

RUN pip install --upgrade pip==24.0

# App requirements --no-cache-dir
RUN pip install  -r requirements.txt
RUN rm requirements.txt
RUN mkdir -p /data/file_upload
RUN chmod -R 777 /data/file_upload
COPY . /app
WORKDIR /app

#Setup API User
RUN addgroup api && adduser -DH -G api apiuser
RUN chown apiuser:api -R /app

EXPOSE 8080
CMD ["su", "-p", "apiuser", "-c", "gunicorn --config=gunicorn.py api.wsgi:application"]
