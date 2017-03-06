#!/usr/bin/python

"""
Mininet Topology for testing Faucet SDN in a complete virtual environment.

+----------------------------+
|                            |
|       FAUCET Controller    |
|                            |
+------(eth4)-------(eth2)---+
        |              |
        |              +------------------+
        |                                  |
+-----(port-4)----------+            +--(eth2)------+
|                       |            |              |
|       OVS         (port-3)------(eth1)   OVS   (int)---(bridged)---(Internet)
|  Emulate Phy Switch   |            |  NFV Switch  |
|                       |            |              |
+--(port-1)---(port-2)--+            +--------------+
       |          |
       |          +----+
       |               |
+--(eth0)---+     +--(eth0)---+
|           |     |           |
| Test Host |     | Test Host |
|    (h1)   |     |    (h2)   |
+-----------+     +-----------+

"""

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.cli import CLI
from mininet.link import Intf
from mininet.log import setLogLevel, info
from mininet.util import quietRun

from time import sleep

EXT_INT = 'enp0s9'


class FaucetTopo(Topo):
    """Topology with 2 switches controlled by Faucet."""

    def __init__(self):
        Topo.__init__(self)

        # Add switches and hosts
        # Faucet controller only supports OpenFlow 1.3
        phy_sw = self.addSwitch('sw1', protocols='OpenFlow13', dpid='1')
        nfv_sw = self.addSwitch('sw2', protocols='OpenFlow13', dpid='2')

        # Nodes receive an IP address by default
        # Set IPs to 0.0.0.0 and configure them later
        faucet = self.addNode('faucet', ip='0.0.0.0')
        dhcp_nfv = self.addNode('dhcp', ip='10.0.0.254', inNamespace=True)
        nat_nfv = self.addNode('nat', ip='10.0.0.1', inNamespace=True)
        ids_nfv = self.addNode('ids', ip='0.0.0.0', inNamespace=True)
        h1 = self.addHost('h1', ip='0.0.0.0')
        h2 = self.addHost('h2', ip='0.0.0.0')

        # Add links
        self.addLink(phy_sw, h1, intfName1='port-1', intfName2='eth0')
        self.addLink(phy_sw, h2, intfName1='port-2', intfName2='eth0')
        self.addLink(phy_sw, nfv_sw, intfName1='port-3', intfName2='eth1')
        self.addLink(phy_sw, faucet, intfName1='port-4', intfName2='eth4')
        self.addLink(nfv_sw, dhcp_nfv, intfName1='int2', intfName2='dhcp-eth0')
        self.addLink(nfv_sw, nat_nfv, intfName1='int3', intfName2='nat-eth0')
        self.addLink(nfv_sw, ids_nfv, intfName1='int4', intfName2='ids-eth0')
        self.addLink(faucet, nfv_sw, intfName1='eth2', intfName2='eth0')


def run():
    "Create the network and run the CLI."
    topo = FaucetTopo()
    # Do not run any controller since we run Faucet inside
    # a dedicated mininet host
    net = Mininet(topo=topo, controller=None)
    net.start()

    # Run provisioning scripts inside each mininet host
    info('*** Provisioning all mininet hosts\n')
    sw1 = net.get('sw1')
    sw2 = net.get('sw2')

    # Faucet controller already runs in root namespace
    # Set the switch to talk to the controller on localhost interface
    sw1.cmd('ovs-vsctl set-controller sw1 tcp:127.0.0.1:6633')
    sw2.cmd('ovs-vsctl set-controller sw2 tcp:127.0.0.1:6633')

    info('*** Checking Faucet status')
    while '(running)' not in quietRun('service faucet status'):
        sleep(1)
        info('.')
        quietRun('service faucet start')
    info('...running\n')

    info('*** Waiting for switch to connect to controller')
    while 'is_connected' not in quietRun('ovs-vsctl show'):
        sleep(1)
        info('.')
    info('...connected\n')

    # Start DHCP server on DHCP NFV
    info('*** Checking dnsmasq running in DHCP NFV')
    dhcp_nfv = net.get('dhcp')
    while '0.0.0.0:67' not in dhcp_nfv.cmd('netstat -an | grep 67'):
        sleep(2)
        info('.')
        dhcp_nfv.cmd('/usr/sbin/dnsmasq')
    info('...started\n')

    # Run DHCP Client on both hosts
    info('*** Waiting for h1 to get DHCP IP address')
    h1 = net.get('h1')
    while '10.0.0' not in h1.cmd('ip addr show eth0 | grep -o 10.0.0.[0-9]'):
        sleep(3)
        info('.')
        h1.cmd('/sbin/udhcpc -nq -t 3 -i eth0')
    info('...got IP\n')

    info('*** Waiting for h2 to get DHCP IP address')
    h2 = net.get('h2')
    while '10.0.0' not in h2.cmd('ip addr show eth0 | grep -o 10.0.0.[0-9]'):
        sleep(3)
        info('.')
        h2.cmd('/sbin/udhcpc -nq -t 3 -i eth0')
    info('...got IP\n')

    # Add the bridged interface to nfv server
    info('*** Moving bridged interface into the NAT NFV..')
    nat_nfv = net.get('nat')
    Intf(EXT_INT, node=nat_nfv)
    sleep(1)
    nat_nfv.cmd('/sbin/dhclient enp0s9')
    info('...done\n')
    info('*** Enabling IP forwarding and Masquerading on NAT NFV.. ')
    nat_nfv.cmd('/sbin/ifconfig lo:1 1.1.1.1/24')
    nat_nfv.cmd('/sbin/ifconfig lo:1 1111::1/64')
    nat_nfv.cmd('/sbin/iptables -t nat -A POSTROUTING -o %s -j MASQUERADE'
                % EXT_INT)
    nat_nfv.cmd('/sbin/sysctl -q -w net.ipv4.ip_forward=1')
    info('...done\n')

    CLI(net)

    nat_nfv.delIntf(EXT_INT)
    info('*** Stopping %i links:' % len(net.links))
    for link in net.links:
        info('.')
        link.stop()
    info('\n')

    info('*** Stopping %i hosts: ' % len(net.hosts))
    for host in net.hosts:
        info(host.name + ' ')
        host.stop(deleteIntfs=True)
        host.terminate()
    info('...done\n')

    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    run()

