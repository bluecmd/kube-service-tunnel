import binascii
import iptc
import pyroute2
import socket


# Prefix tunnel interfaces with this string
TUNNEL_PREFIX = 'ts'
BUCKETS = 2
MODE = 'mpls'


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

    def __init__(self, service):
        self.service = service

    def enact(self, endpoint_map, ip):
        print 'REFRESH', self.service

        # TODO research what the state of per-route encap is. that would be
        # extremely nice to use here instead of having a lot of GRE interfaces.
        #ip.route('add', dst=self.service.tunnel_ip, oif=2, encap={'type': 'mpls', 'labels': '200/300'})

        dst = self.service.tunnel_ip + '/32'

        # TODO: only apply the actual changes we need
        for table in range(BUCKETS):
            try:
                ip.route('del', table=(table+1), dst=dst)
            except pyroute2.netlink.exceptions.NetlinkError:
                pass

        endpoints = endpoint_map[self.service]
        if not endpoints:
            del endpoint_map[self.service]
            return

        # TODO: do actual balancing
        endpoint = endpoints.keys()[0]
        ifx = endpoints[endpoint]
        for table in range(BUCKETS):
            if MODE == 'gre':
                ip.route('add', table=(table+1), dst=dst, oif=ifx)
            if MODE == 'mpls':
                ip.route('add', table=(table+1), dst=dst, gateway=endpoint,
                        encap={'type': 'mpls', 'labels': 100})


class AddEndpoint(object):
    """Set up a new tunnel to the new endpoint."""

    def __init__(self, service, endpoint):
        self.service = service
        self.endpoint = endpoint

    def enact(self, endpoint_map, ip):
        print 'NEW_TUNNEL', self.service, self.endpoint
        ifx = None
        if MODE == 'gre':
            ifname = TUNNEL_PREFIX + binascii.hexlify(
                    socket.inet_aton(self.endpoint))
            ip.link('add', ifname=ifname, kind='gre', gre_remote=self.endpoint)
            ifx = ip.link_lookup(ifname=ifname)[0]
            ip.link('set', state='up', index=ifx)
        endpoint_map[self.service][self.endpoint] = ifx


class RemoveEndpoint(object):
    """Remove tunnel to an old endpoint."""

    def __init__(self, service, endpoint):
        self.service = service
        self.endpoint = endpoint

    def enact(self, endpoint_map, ip):
        print 'REMOVE_TUNNEL', self.service, self.endpoint
        ifx = endpoint_map[self.service][self.endpoint]
        if ifx:
            ip.link('delete', index=ifx)
        del endpoint_map[self.service][self.endpoint]
