#!/usr/bin/env python

import collections
import iptc
import pykube
import random
import time


INGRESS_CHAIN = 'TUNNEL-INGRESS'
FILTER_CHAIN = 'TUNNEL-FILTER'
TUNNEL_ANNOTATION = 'cmd.nu/tunnel'
BUCKETS = 2


Service = collections.namedtuple('Service', ('name', 'namespace'))
AddService = collections.namedtuple(
        'AddService', ('service', 'tunnel_ip'))
RemoveService = collections.namedtuple(
        'RemoveService', ('service', 'tunnel_ip'))
RefreshEndpoints = collections.namedtuple(
        'RefreshEndpoints', ('service', 'endpoints'))


def create_ingress_chain():
    """Ingress chain marks all packets for tunnel ingress."""
    rule = iptc.Rule()
    t = rule.create_target('HMARK')

    t.hmark_tuple = 'src,dst,sport,dport'
    t.hmark_mod = str(BUCKETS)
    t.hmark_offset = '1'
    t.hmark_rnd = str(random.randint(1,65535))

    mangle_table = iptc.Table(iptc.Table.MANGLE)
    ingress_chain = iptc.Chain(mangle_table, INGRESS_CHAIN)
    if mangle_table.is_chain(INGRESS_CHAIN):
        ingress_chain.flush()
    else:
        ingress_chain = mangle_table.create_chain(INGRESS_CHAIN)
    ingress_chain.insert_rule(rule)


def create_ingress_filter_chain():
    """Ingress filter chain matches the tunnel VIPs."""
    mangle_table = iptc.Table(iptc.Table.MANGLE)
    filter_chain = iptc.Chain(mangle_table, FILTER_CHAIN)
    if mangle_table.is_chain(FILTER_CHAIN):
        filter_chain.flush()
    else:
        filter_chain = mangle_table.create_chain(FILTER_CHAIN)

    return filter_chain


def register_ingress():
    """Insert PREROUTING rule for packets to move through the ingress filter."""
    chain = iptc.Chain(iptc.Table(iptc.Table.MANGLE), 'PREROUTING')
    for rule in chain.rules:
        if rule.target.name == FILTER_CHAIN:
            # Already registered
            return
    rule = iptc.Rule()
    t = rule.create_target(FILTER_CHAIN)
    chain.insert_rule(rule)


def get_services(api):
    """Return set of (service, tunnel-ip)."""
    filters = set()
    for svc in pykube.Service.objects(api).filter(namespace=pykube.all):
        annotations = svc.metadata.get('annotations', {})
        tunnel_ip = annotations.get(TUNNEL_ANNOTATION, None)
        if tunnel_ip is None:
            continue
        filters.add((Service(svc.name, svc.metadata['namespace']), tunnel_ip))
    return filters


def get_endpoints(api, services):
    """Return map of (service) = set(ips)."""
    endpoints = {}
    for endp in pykube.Endpoint.objects(api).filter(namespace=pykube.all):
        svc = Service(endp.metadata['name'], endp.metadata['namespace'])
        if not svc in services:
            continue
        ips = set()
        subsets = endp.obj['subsets']
        for s in subsets:
            for address in s['addresses']:
                ips.add(address['ip'])
        endpoints[svc] = ips
    return endpoints


def calculate_filter_changes(api, service_map):
    # Calculate filter changes
    new_services = get_services(api)
    current_services = set(service_map.keys())
    removed_services = current_services - new_services
    added_services = new_services - current_services
    for svc, tunnel_ip in added_services:
        yield AddService(svc, tunnel_ip)
    for svc, tunnel_ip in removed_services:
        yield RemoveService(svc, tunnel_ip)


def calculate_routing_changes(api, endpoint_map, service_filter):
    # Calculate routing balancing changes
    new_endpoints_map = get_endpoints(api, service_filter)

    # Endppint changes in already known, or new, services
    for svc, new_endpoints in new_endpoints_map.iteritems():
        current_endpoints = endpoint_map.get(svc, set())
        if current_endpoints != new_endpoints:
            yield RefreshEndpoints(svc, new_endpoints)

    # Purge empty endpoint services
    removed_services = set(endpoint_map.keys()) - set(new_endpoints_map.keys())
    for svc in removed_services:
        yield RefreshEndpoints(svc, set())


if __name__ == '__main__':
    print 'Creating ingress chain'
    create_ingress_chain()

    print 'Creating ingress filter chain'
    filter_chain = create_ingress_filter_chain()

    print 'Registering ingress'
    register_ingress()

    print 'Starting poll loop for Kubernetes services'
    kube_creds = pykube.KubeConfig.from_file('/home/bluecmd/.kube/config')
    #kube_creds = pykube.KubeConfig.from_service_account()
    api = pykube.HTTPClient(kube_creds)

    # Map 1: Used to filter on IPs to ingress in the tunnels
    # Stored as (service, tunnel-ip) = iptc.Rule
    service_map = {}

    # Map 2: Used to balance among endpoints (pods)
    # Stored as (service) = set(pods)
    # On changes on the above, recalculate the route maps
    endpoint_map = {}

    while True:
        filter_changes = calculate_filter_changes(api, service_map)
        for change in filter_changes:
            key = (change.service, change.tunnel_ip)
            if type(change) == AddService:
                service_map[key] = 1
                print 'ADD', change.service, change.tunnel_ip
            elif type(change) == RemoveService:
                del service_map[key]
                print 'REMOVE', change.service, change.tunnel_ip

        service_filter = {svc for svc, _ in service_map}
        routing_changes = calculate_routing_changes(
                api, endpoint_map, service_filter)

        for change in routing_changes:
            if type(change) == RefreshEndpoints:
                print 'REFRESH', change.service, change.endpoints
                if not change.endpoints:
                    del endpoint_map[change.service]
                    continue
                endpoint_map[change.service] = change.endpoints

        time.sleep(1)
