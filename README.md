# kube-service-tunnel

Goal: Have externally routable IPs end up as normal IP packets inside pods.

Implementation: Using GRE tunnels on ingressing traffic torward these IPs, tunnel the traffic to inside the pods.

PoC:
```
#!/bin/sh
ip netns exec test-pod ip tunnel del test-svc
ip netns exec test-pod ip tunnel add test-svc mode gre remote any local 10.188.29.79
ip netns exec test-pod ip addr add 10.188.255.10/32 dev test-svc
ip netns exec test-pod ip link set up dev test-svc

ip tunnel del test-svc
ip tunnel add test-svc mode gre remote 10.188.29.79 local any
ip addr add 10.188.255.9/32 dev test-svc
ip link set up dev test-svc
ip ro add 10.188.255.10 dev test-svc

echo Remember to disable rp_filter

ping 10.188.255.10
```
