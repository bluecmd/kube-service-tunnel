
class AddService(object):

    def __init__(self, service, tunnel_ip):
        self.service = service
        self.tunnel_ip = tunnel_ip

    def enact(self, service_map, filter_chain):
        print 'ADD', self.service, self.tunnel_ip
        key = (self.service, self.tunnel_ip)
        service_map[key] = 1


class RemoveService(object):

    def __init__(self, service, tunnel_ip):
        self.service = service
        self.tunnel_ip = tunnel_ip

    def enact(self, service_map, filter_chain):
        print 'REMOVE', self.service, self.tunnel_ip
        key = (self.service, self.tunnel_ip)
        del service_map[key]


class RefreshEndpoints(object):

    def __init__(self, service, endpoints):
        self.service = service
        self.endpoints = endpoints

    def enact(self, endpoint_map):
        print 'REFRESH', self.service, self.endpoints
        if not self.endpoints:
            del endpoint_map[self.service]
            return
        endpoint_map[self.service] = self.endpoints
