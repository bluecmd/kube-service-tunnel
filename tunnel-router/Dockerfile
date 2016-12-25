FROM python:3-alpine

RUN apk --update add gcc linux-headers musl-dev iptables
RUN pip3 install python-iptables pyroute2 pykube

ADD start.sh /
ADD *.py /router/

# TODO: python-iptables seems to have trouble finding the libraries
RUN ln -sf /usr/lib/libxtables.so.*.*.* /usr/lib//libxtables.so
RUN ln -sf /usr/lib/libiptc.so.*.*.* /usr/lib/libiptc.so
RUN ln -sf /usr/lib /usr/lib64

CMD ["/start.sh"]
