FROM python:2-alpine

RUN apk --update add gcc linux-headers musl-dev
RUN pip install python-iptables pyroute2 pykube

CMD ["/start.sh"]
