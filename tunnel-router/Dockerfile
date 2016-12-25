FROM python:2-alpine

RUN apk --update add gcc linux-headers musl-dev iptables
RUN pip install python-iptables pyroute2 pykube

ADD start.sh /
ADD *.py /router/


CMD ["/start.sh"]
