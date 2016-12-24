import binascii
import iptc
import socket


# Prefix tunnel interfaces with this string
TUNNEL_PREFIX = 'ts'


class AddService(object):
    """Start ingressing a tunnel IP for a service."""

    def __init__(self, service):
        self.service = service

    def enact(self, service_map, filter_chain, ingress_chain):
        print 'ADD', self.service

        rule = iptc.Rule()
        rule.dst = self.service.tunnel_ip
        t = rule.create_target(ingress_chain.name)
        m = rule.create_match("comment")
        m.comment = "Tunnel ingress for (%s, %s)" % (
                self.service.name, self.service.namespace)
        filter_chain.insert_rule(rule)

        service_map[self.service] = rule


class RemoveService(object):
    """Stop ingressing a tunnel IP for a service."""

    def __init__(self, service):
        self.service = service

    def enact(self, service_map, filter_chain, ingress_chain):
        print 'REMOVE', self.service
        rule = service_map[self.service]
        filter_chain.delete_rule(rule)
        del service_map[self.service]


class RefreshEndpoints(object):
    """Recalculate all the routing buckets for a service."""

    def __init__(self, service, endpoints):
        self.service = service
        self.endpoints = endpoints

    def enact(self, endpoint_map, ip):
        print 'REFRESH', self.service, self.endpoints
        print 'Has %d targets to balance' % len(self.endpoints)
        if not self.endpoints:
            del endpoint_map[self.service]
            return


class AddEndpoint(object):
    """Set up a new tunnel to the new endpoint."""

    def __init__(self, service, endpoint):
        self.service = service
        self.endpoint = endpoint

    def enact(self, endpoint_map, ip):
        print 'NEW_TUNNEL', self.service, self.endpoint
        ifname = TUNNEL_PREFIX + binascii.hexlify(
                socket.inet_aton(self.endpoint))
        ip.link('add', ifname=ifname, kind='gre', gre_remote=self.endpoint)
        ip.link('set', state='up', ifname=ifname)
        #ip.route('add', dst=self.service.tunnel_ip, oif=2, encap={'type': 'mpls', 'labels': '200/300'})
        endpoint_map[self.service][self.endpoint] = ifname


class RemoveEndpoint(object):
    """Remove tunnel to an old endpoint."""

    def __init__(self, service, endpoint):
        self.service = service
        self.endpoint = endpoint

    def enact(self, endpoint_map, ip):
        print 'REMOVE_TUNNEL', self.service, self.endpoint
        ifname = endpoint_map[self.service][self.endpoint]
        ip.link('delete', ifname=ifname)
        del endpoint_map[self.service][self.endpoint]
