import iptc


class AddService(object):
    """Start ingressing a tunnel IP for a service."""

    def __init__(self, service, tunnel_ip):
        self.service = service
        self.tunnel_ip = tunnel_ip

    def enact(self, service_map, filter_chain, ingress_chain):
        print 'ADD', self.service, self.tunnel_ip

        rule = iptc.Rule()
        rule.dst = self.tunnel_ip
        t = rule.create_target(ingress_chain.name)
        m = rule.create_match("comment")
        m.comment = "Tunnel ingress for (%s, %s)" % (
                self.service.name, self.service.namespace)
        filter_chain.insert_rule(rule)

        key = (self.service, self.tunnel_ip)
        service_map[key] = rule


class RemoveService(object):
    """Stop ingressing a tunnel IP for a service."""

    def __init__(self, service, tunnel_ip):
        self.service = service
        self.tunnel_ip = tunnel_ip

    def enact(self, service_map, filter_chain, ingress_chain):
        print 'REMOVE', self.service, self.tunnel_ip
        key = (self.service, self.tunnel_ip)
        rule = service_map[key]
        filter_chain.delete_rule(rule)
        del service_map[key]


class RefreshEndpoints(object):
    """Recalculate all the routing buckets for a service."""

    def __init__(self, service, endpoints):
        self.service = service
        self.endpoints = endpoints

    def enact(self, endpoint_map):
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

    def enact(self, endpoint_map):
        print 'NEW_TUNNEL', self.service, self.endpoint
        endpoint_map[self.service][self.endpoint] = 1


class RemoveEndpoint(object):
    """Remove tunnel to an old endpoint."""

    def __init__(self, service, endpoint):
        self.service = service
        self.endpoint = endpoint

    def enact(self, endpoint_map):
        print 'REMOVE_TUNNEL', self.service, self.endpoint
        del endpoint_map[self.service][self.endpoint]
