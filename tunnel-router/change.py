import binascii
import collections
import errno
import iptc
import os
import pyroute2
import socket


# Prefix tunnel interfaces with this string
TUNNEL_PREFIX = os.environ.get('TUNNEL_ROUTER_TUNNEL_PREFIX', 'ts')
BUCKETS = int(os.environ.get('TUNNEL_ROUTER_BUCKETS', '2'))
MODE = os.environ.get('TUNNEL_ROUTER_MODE', 'mpls')

Interface = collections.namedtuple('Interface', ('ifx', 'internal'))


class AddService(object):
    """Start ingressing a tunnel IP for a service."""

    def __init__(self, service):
        self.service = service

    def enact(self, service_map, filter_chain, ingress_chain):
        print('ADD', self.service)

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
        print('REMOVE', self.service)
        rule = service_map[self.service]
        filter_chain.delete_rule(rule)
        del service_map[self.service]


class RefreshEndpoints(object):
    """Recalculate all the routing buckets for a service."""

    def __init__(self, service):
        self.service = service

    def enact(self, endpoint_map, ip):
        print('REFRESH', self.service)

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
        endpoint = list(endpoints.keys())[0]
        iface = endpoints[endpoint][0]
        for table in range(BUCKETS):
            if MODE == 'gre':
                ip.route('add', table=(table+1), dst=dst, oif=iface.ifx)
            if MODE == 'mpls':
                ip.route('add', table=(table+1), dst=dst, gateway=endpoint,
                        encap={'type': 'mpls', 'labels': 100})


class AddEndpoint(object):
    """Set up a new tunnel to the new endpoint."""

    def __init__(self, service, endpoint):
        self.service = service
        self.endpoint = endpoint

    def enact(self, endpoint_map, ip):
        print('NEW_TUNNEL', self.service, self.endpoint)
        ifs = []

        # Open network namespace inside the endpoint if we have it.
        # If the pod is not local, we do not have it - but another tunnel
        # router will.
        netns = (pyroute2.NetNS(self.endpoint.networkNs)
                if self.endpoint.networkNs else None)

        if MODE == 'gre':
            ifname = TUNNEL_PREFIX + str(binascii.hexlify(
                    socket.inet_aton(self.endpoint.ip)), 'utf-8')
            try:
                ip.link('add', ifname=ifname, kind='gre',
                        gre_remote=self.endpoint.ip)
            except pyroute2.netlink.exceptions.NetlinkError as e:
                if e.code != errno.EEXIST:
                    raise
            ifx = ip.link_lookup(ifname=ifname)[0]
            ifs.append(Interface(ifx, internal=False))
            ip.link('set', state='up', index=ifx)

            if netns:
                print('NEW_POD_TUNNEL', self.service, self.endpoint)
                ifname = self.service.name
                try:
                    netns.link('add', ifname=ifname, kind='gre',
                            gre_local=self.endpoint.ip)
                except pyroute2.netlink.exceptions.NetlinkError as e:
                    if e.code != errno.EEXIST:
                        raise
                ifx = netns.link_lookup(ifname=ifname)[0]
                ifs.append(Interface(ifx, internal=True))
                try:
                    netns.addr('add', address=self.service.tunnel_ip,
                            prefixlen=32, index=ifx)
                except pyroute2.netlink.exceptions.NetlinkError as e:
                    if e.code != errno.EEXIST:
                        raise
                netns.link('set', state='up', index=ifx)
        if netns:
            netns.close()
        endpoint_map[self.service][self.endpoint] = ifs


class RemoveEndpoint(object):
    """Remove tunnel to an old endpoint."""

    def __init__(self, service, endpoint):
        self.service = service
        self.endpoint = endpoint

    def enact(self, endpoint_map, ip):
        print('REMOVE_TUNNEL', self.service, self.endpoint)

        # Open network namespace inside the endpoint if we have it.
        # If the pod is not local, we do not have it - but another tunnel
        # router will.
        netns = None
        try:
            netns = (pyroute2.NetNS(self.endpoint.networkNs)
                if self.endpoint.networkNs else None)
        except FileNotFoundError:
            # If the namespace has gone away the interface is also gone
            pass

        for iface in endpoint_map[self.service][self.endpoint]:
            if iface.internal and netns:
                print('REMOVE_POD_IFACE', self.service, self.endpoint, iface)
                netns.link('delete', index=iface.ifx)
            else:
                print('REMOVE_HOST_IFACE', self.service, self.endpoint, iface)
                ip.link('delete', index=iface.ifx)

        if netns:
            netns.close()
        del endpoint_map[self.service][self.endpoint]
