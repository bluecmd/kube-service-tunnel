#!/usr/bin/env python

import iptc
import pykube
import random
import time


INGRESS_CHAIN = 'TUNNEL-INGRESS'
FILTER_CHAIN = 'TUNNEL-FILTER'
TUNNEL_ANNOTATION = 'cmd.nu/tunnel'
BUCKETS = 2


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
    # Stored as (service, namespace, tunnel-ip) = iptc.Rule
    filters = set()
    for svc in pykube.Service.objects(api).filter(namespace=pykube.all):
        annotations = svc.metadata.get('annotations', {})
        tunnel_ip = annotations.get(TUNNEL_ANNOTATION, None)
        if tunnel_ip is None:
            continue
        filters.add((svc.name, svc.metadata['namespace'], tunnel_ip))
    return filters


def get_endpoints(api, services):
    # Stored as (service, namespace) = set(pods)
    endpoints = {}
    for endp in pykube.Endpoint.objects(api).filter(namespace=pykube.all):
        svc = endp.metadata['name']
        namespace = endp.metadata['namespace']
        if not (svc, namespace) in services:
            continue
        ips = set()
        subsets = endp.obj['subsets']
        for s in subsets:
            for address in s['addresses']:
                ips.add(address['ip'])
        endpoints[(svc, namespace)] = ips
    return endpoints


def calculate_filter_changes(api, service_map):
    # Calculate filter changes
    changes = []

    new_services = get_services(api)
    current_services = set(service_map.keys())
    removed_services = current_services - new_services
    added_services = new_services - current_services
    for entry in removed_services:
        changes.append(('Removed service', entry))
        del service_map[entry]
    for entry in added_services:
        changes.append(('Added service', entry))
        service_map[entry] = 1
    return changes


def calculate_routing_changes(api, endpoint_map, service_filter):
    # Calculate routing balancing changes
    changes = []
    new_endpoints_map = get_endpoints(api, service_filter)

    # Endppint changes in already known, or new, services
    for key, new_endpoints in new_endpoints_map.iteritems():
        current_endpoints = endpoint_map.get(key, set())
        added_endpoints = new_endpoints - current_endpoints
        removed_endpoints = current_endpoints - new_endpoints
        for endpoint in added_endpoints:
            changes.append(('Added routing endpoint', endpoint))
        for endpoint in removed_endpoints:
            changes.append(('Removed routing endpoint', endpoint))
        endpoint_map[key] = new_endpoints

    # Removed services
    to_remove = set(endpoint_map.keys()) - set(new_endpoints_map.keys())
    for key in to_remove:
        for endpoint in endpoint_map[key]:
            changes.append(('Removed routing endpoint', endpoint))
        del endpoint_map[key]
    return changes


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
    # Stored as (service, namespace, tunnel-ip) = iptc.Rule
    service_map = {}

    # Map 2: Used to balance among endpoints (pods)
    # Stored as (service, namespace) = set(pods)
    # On changes on the above, recalculate the route maps
    endpoint_map = {}

    while True:
        filter_changes = calculate_filter_changes(api, service_map)
        service_filter = {
                (svc, ns) for svc, ns, _ in service_map}
        routing_changes = calculate_routing_changes(
                api, endpoint_map, service_filter)

        print filter_changes
        print routing_changes

        time.sleep(1)
