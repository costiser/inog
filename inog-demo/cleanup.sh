#!/bin/bash

# Run Mininet's cleanup utility
sudo mn -c

# Delete all existing network namespaces
ip netns | xargs -r -t -n 1 ip netns del

# Delete all special-cases interfaces (these are veth used for the virtual topology)
ip link | egrep -o "[dhcpnatids]{3,4}-eth[01]" | xargs -r -t -n 1 ip link del
ip link | egrep -o "port-[1234]" | xargs -r -t -n 1 ip link del
ip link | egrep -o "int[1234]" | xargs -r -t -n 1 ip link del
