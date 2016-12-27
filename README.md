# kube-service-tunnel

Goal: Have externally routable IPs end up as normal IP packets inside pods.

Implementation: Using tunnels on ingressing traffic torward these IPs, tunnel the traffic to inside the pods.

State:
- GRE verified working w/ Calico (caveat https://github.com/projectcalico/felix/issues/1248)
- MPLS does not configure pods yet (pending https://github.com/coreos/bugs/issues/1730).

## Getting Started

1. `kubectl create -f tunnel-router.yaml`
2. Annotate a service with `cmd.nu/tunnel: $ip` where $ip is an IP that is routed towards your nodes.

Done! You should now be able to access the pod normally through the tunnel'd IP. If your pod listens to `0.0.0.0`/`::0` everything should just work.

## Modes of Operation

kube-service-tunnel preferred mode uses lwtunnels to avoid creating a massive
amount of tunnel interfaces. Instead, encapsulation is specified on a per-route
basis. For this to work you need a kernel with CONFIG\_LWTUNNEL (newer than 4.3).

Alternatively kube-service-tunnel can work using GRE tunnels using ordinary
tunnel interfaces.

Currently, as far as I know, the only supported encapsulation for lwtunnels
is MPLS, which limits the usability of this mode to node-local encapsulation.
If you have other router infrastructure set up to deliver traffic to your nodes
(like [`svc-bgp`](https://github.com/dhtech/kubernetes/tree/master/svc-bgp))
this will work just fine. Otherwise you might want to use the GRE mode.

Due to the restrictions above the following applies:

 * In MPLS mode you are responsible to get the packet to a serving node.

 * In GRE mode a lot of interfaces will be created (one per endpoint).

**If anybody knows more about lwtunnels and how to use it to encapsulate inside
an IP packet, please let me know.**

### Load Balancing

`TODO: Explain this in more detail`

Using iptables' `HMARK` target, an incoming packet receives a hash that is used to select among a configurable number of routing tables. Each routing table contains a route for every active tunnel IP. One endpoint will most likely be in multiple buckets, and if you have more endpoints than buckets you will have no traffic to the excess part of your endpoints.

### Configuration of Endpoints

When a new endpoint is discovered that belongs to a service with a tunnel IP, that endpoint's pod must be reconfigured to have the tunnel IP available. This is done in a container runtime dependent way (due to network namespace ID lookup), and currently only Docker is supported.

If the mode of operation is GRE: A GRE interface is created inside the network namespace and the tunnel IP is attached to it.

If the mode of operation is MPLS: An MPLS decapsulation rule is added to pop the label `100` and deliver those packages locally. The tunnel IP is added to the looback inteface.

### Example Cluster Layout

![Example Cluster Layout](https://storage.googleapis.com/bluecmd/kube-service-tunnel/cluster-layout.svg)

An example cluster would have a sane number of nodes marked to handle ingress traffic, here shown with a `node=tunnel` label. Those nodes would announce themselves to the DC routers in a suitable manner, for exmaple using BGP + BFD.

The cluser ingress nodes would then be responsible for handling routing of incoming packets towards a suitable endpoint. The routing should be done such a way that when a tunnel node fails, the next tunnel node should pick the same routing path as the failed node.

Note: In the current version the `HMARK` seed is random, which voids the previous paragraph. It is on the road map to store routing decisions in the service objects themselves to allow for hitless resumption of routing.

## Example Service

```
apiVersion: v1
kind: Service
metadata:
  annotations:
    # This is the IP that will be tunneled into the pod.
    # The pod will also get this IP added to a pod-local interface.
    cmd.nu/tunnel: 1.2.3.4
  labels:
    k8s-app: test
  name: test
spec:
  ports:
  - port: 3000
    protocol: TCP
    targetPort: 3000
  selector:
    k8s-app: test
```

## Roadmap

Features planned:

 - Tests :-)
 - Full MPLS support
 - Draining of endpoints
 - Hit-less failover
 
Ideas that may come to the roadmap if anyone needs them:

 - Network policy support
 - Accounting

## FAQ

Frequently asked questions and answers.

### Why not use ...

There are many ways one could solve the problem discussed here. Let's address why those solutions didn't work for me.

#### NodePort

For a while this is what I used. However, it is bulky when used in production. It lacks isolation between services - i.e. a service cannot use the same port, and most obviously it doesn't support the well-known ports. Having the end user having to type `https://cmd.nu:30000` would not be a good end user story.

Lastly, it doesn't scale. You will run out of ports soon enough.

#### LoadBalancer

Same issue as above, but now requires an unknown external agent to forward the TCP connections to the assigned NodePort. Due to this forwarding you will lose the original TCP connection and the metadata about it - such as source-IP.

#### ClusterIP

Having the Cluster IP routable from the Internet is something we tried during Dreamhack Winter 2016. It worked reasonably well, and is the closest match to what I would consider production ready yet. Sadly, there are [assumptions](https://github.com/kubernetes/kubernetes/issues/7433) around how cluster IPs work and they are not easy to work around. 

You would also find yourself wasting a lot of routable IPv4 addresses for things that are only cluster internal.

#### Directly Routed IPs

Basically, remove the tunnel interfaces and just route the traffic via normal routing.

This would theoretically work, but a lot of fancy operations that you would like to have - like client affinity, draining, and such would be borderline impossible to implement. The normal multipath routing support in Linux is quite wild-west.
