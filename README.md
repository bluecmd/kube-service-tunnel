# kube-service-tunnel

Goal: Have externally routable IPs end up as normal IP packets inside pods.

Implementation: Using tunnels on ingressing traffic torward these IPs, tunnel the traffic to inside the pods.

## Modes of Operation

kube-service-tunnel preferred mode uses lwtunnels to avoid creating a massive
amount of tunnel interfaces. Instead, encapsulation is specified on a per-route
basis. For this to work you need a kernel with CONFIG\_LWTUNNEL (newer than 4.3).

Alternatively kube-service-tunnel can work using GRE tunnels using ordinary
tunnel interfaces.

Currently, as far as I know, the only supported encapsulation for lwtunnels
is MPLS, which limits the usability of this mode to node-local encapsulation.
If you have other router infrastructure set up to deliver traffic to your nodes
(like (`svc-bgp`)[https://github.com/dhtech/kubernetes/tree/master/svc-bgp])
this will work just fine. Otherwise you might want to use the GRE mode.

Due to the restrictions above the following applies:

 * In MPLS mode you are responsible to get the packet to a serving node.

 * In GRE mode a lot of interfaces will be created (one per endpoint).

**If anybody knows more about lwtunnels and how to use it to encapsulate inside
an IP packet, please let me know.**
