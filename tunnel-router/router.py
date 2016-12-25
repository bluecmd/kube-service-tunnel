#!/usr/bin/env python

import collections
import iptc
import os
import pykube
import pyroute2
import random
import time
import traceback

import change


INGRESS_CHAIN = os.environ.get(
        'TUNNEL_ROUTER_INGRESS_CHAIN', 'TUNNEL-INGRESS')
FILTER_CHAIN = os.environ.get(
        'TUNNEL_ROUTER_FILTER_CHAIN', 'TUNNEL-FILTER')
TUNNEL_ANNOTATION = os.environ.get(
        'TUNNEL_ROUTER_TUNNEL_ANNOTATION', 'cmd.nu/tunnel')
TABLE_OFFSET = os.environ.get(
        'TUNNEL_ROUTER_TABLE_OFFSET', '1')


Service = collections.namedtuple('Service', ('name', 'namespace', 'tunnel_ip'))


def create_ingress_chain():
    """Ingress chain marks all packets for tunnel ingress."""
    rule = iptc.Rule()
    t = rule.create_target('HMARK')

    t.hmark_tuple = 'src,dst,sport,dport'
    t.hmark_mod = str(change.BUCKETS)
    t.hmark_offset = TABLE_OFFSET
    t.hmark_rnd = str(random.randint(1, 65535))

    mangle_table = iptc.Table(iptc.Table.MANGLE)
    ingress_chain = iptc.Chain(mangle_table, INGRESS_CHAIN)
    if mangle_table.is_chain(INGRESS_CHAIN):
        ingress_chain.flush()
    else:
        ingress_chain = mangle_table.create_chain(INGRESS_CHAIN)
    ingress_chain.insert_rule(rule)
    return ingress_chain


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
    """Insert rules for packets to move through the ingress filter."""
    for c in ['PREROUTING', 'OUTPUT']:
        chain = iptc.Chain(iptc.Table(iptc.Table.MANGLE), c)
        for rule in chain.rules:
            if rule.target.name == FILTER_CHAIN:
                # Already registered
                return
        rule = iptc.Rule()
        t = rule.create_target(FILTER_CHAIN)
        chain.insert_rule(rule)


def get_services(api):
    """Return set of services."""
    filters = set()
    for svc in pykube.Service.objects(api).filter(namespace=pykube.all):
        annotations = svc.metadata.get('annotations', {})
        tunnel_ip = annotations.get(TUNNEL_ANNOTATION, None)
        if tunnel_ip is None:
            continue
        filters.add((Service(svc.name, svc.metadata['namespace'], tunnel_ip)))
    return filters


def get_endpoints(api, services):
    """Return map of (service) = set(ips)."""

    # Create a fast-lookup for (svc, ns) -> Service object
    lookup_map = {(x.name, x.namespace): x for x in services}

    endpoints = {}
    for endp in pykube.Endpoint.objects(api).filter(namespace=pykube.all):
        svc = lookup_map.get(
                (endp.metadata['name'], endp.metadata['namespace']), None)
        if svc is None:
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
    for svc in added_services:
        yield change.AddService(svc)
    for svc in removed_services:
        yield change.RemoveService(svc)


def calculate_routing_changes(api, endpoint_map, service_filter):
    # Calculate routing balancing changes
    new_endpoints_map = get_endpoints(api, service_filter)

    # Endppint changes in already known, or new, services
    for svc, new_endpoints in new_endpoints_map.iteritems():
        current_endpoints = set(endpoint_map.get(svc, dict()).keys())
        added_endpoints = new_endpoints - current_endpoints
        removed_endpoints = current_endpoints - new_endpoints
        for endpoint in added_endpoints:
            yield change.AddEndpoint(svc, endpoint)
        for endpoint in removed_endpoints:
            yield change.RemoveEndpoint(svc, endpoint)
        if current_endpoints != new_endpoints:
            yield change.RefreshEndpoints(svc)

    # Purge empty endpoint services
    removed_services = set(endpoint_map.keys()) - set(new_endpoints_map.keys())
    for svc in removed_services:
        for endpoint in endpoint_map[svc].keys():
            yield change.RemoveEndpoint(svc, endpoint)
        yield change.RefreshEndpoints(svc)


def purge_old_tunnels():
    ip = pyroute2.IPRoute()
    for link in ip.get_links():
        ifname = link.get_attr('IFLA_IFNAME')
        if ifname.startswith(change.TUNNEL_PREFIX):
            ip.link('del', ifname=ifname)


def create_iproute_rules():
    ip = pyroute2.IPRoute()
    for i in range(change.BUCKETS):
        try:
            ip.rule('add', table=(i+1), fwmark=(i+1))
        except pyroute2.netlink.exceptions.NetlinkError:
            # Assume it already exists
            pass


def loop(ingress_chain, filter_chain):
    print 'Starting poll loop for Kubernetes services'
    kube_creds = None
    if 'KUBECONFIG' in os.environ:
        kube_creds = pykube.KubeConfig.from_file(os.environ['KUBECONFIG'])
    else:
        kube_creds = pykube.KubeConfig.from_service_account()
    api = pykube.HTTPClient(kube_creds)

    # Map 1: Used to filter on IPs to ingress in the tunnels
    # Stored as (service, tunnel-ip) = iptc.Rule
    service_map = {}

    # Map 2: Used to balance among endpoints (pods)
    # Stored as (service) = {pod: tunnel}
    # On changes on the above, recalculate the route maps
    endpoint_map = collections.defaultdict(dict)

    ip = pyroute2.IPRoute()
    while True:
        filter_changes = calculate_filter_changes(api, service_map)
        for c in filter_changes:
            c.enact(service_map, filter_chain, ingress_chain)

        routing_changes = calculate_routing_changes(
                api, endpoint_map, service_map.keys())

        for c in routing_changes:
            c.enact(endpoint_map, ip)

        time.sleep(1)


if __name__ == '__main__':
    print 'Creating ingress chain'
    ingress_chain = create_ingress_chain()

    print 'Creating ingress filter chain'
    filter_chain = create_ingress_filter_chain()

    print 'Registering ingress'
    register_ingress()

    print 'Purging old tunnels'
    purge_old_tunnels()

    print 'Creating iproute rules'
    create_iproute_rules()

    while True:
        try:
            loop(ingress_chain, filter_chain)
        except KeyboardInterrupt:
            break
        except:
            print 'Exception in main loop:'
            traceback.print_exc()
