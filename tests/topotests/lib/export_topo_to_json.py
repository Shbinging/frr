#!/usr/bin/env python3
# SPDX-License-Identifier: ISC
#
# export_topo_to_json.py
# Simple utility to export topology structure from Topogen to JSON
#

"""
Simple topology exporter that extracts router and switch connection
information from a Topogen object and outputs it as JSON.

This tool only exports the network structure (nodes and links), not
the full configuration. The output is for documentation purposes and
does not need to be re-importable by topojson.
"""

import json
from collections import OrderedDict


def export_topology_to_json(tgen, output_path):
    """
    Export topology structure to JSON file.
    
    Args:
        tgen: Topogen object with built topology
        output_path: Path to output JSON file
    
    Returns:
        Dictionary with topology data
    """
    topo_data = OrderedDict()
    
    # Extract routers
    routers = OrderedDict()
    for name, gear in sorted(tgen.gears.items()):
        # Check if it's a router (has 'routertype' attribute or is TopoRouter)
        if hasattr(gear, 'routertype') or gear.__class__.__name__ == 'TopoRouter':
            router_info = {
                'type': 'router',
                'links': {}
            }
            
            # Extract links
            for ifname, (peer_gear, peer_ifname) in gear.links.items():
                peer_name = peer_gear.name
                router_info['links'][peer_name] = {
                    'interface': ifname,
                    'peer_interface': peer_ifname
                }
            
            routers[name] = router_info
    
    # Extract switches
    switches = OrderedDict()
    for name, gear in sorted(tgen.gears.items()):
        # Check if it's a switch (has no 'routertype' and is TopoSwitch)
        if gear.__class__.__name__ == 'TopoSwitch':
            switch_info = {
                'type': 'switch',
                'links': {}
            }
            
            # Extract links
            for ifname, (peer_gear, peer_ifname) in gear.links.items():
                peer_name = peer_gear.name
                switch_info['links'][peer_name] = {
                    'interface': ifname,
                    'peer_interface': peer_ifname
                }
            
            switches[name] = switch_info
    
    # Build final structure
    if routers:
        topo_data['routers'] = routers
    if switches:
        topo_data['switches'] = switches
    
    # Add metadata
    topo_data['metadata'] = {
        'total_routers': len(routers),
        'total_switches': len(switches),
        'exported_from': tgen.modname
    }
    
    # Write to file
    with open(output_path, 'w') as f:
        json.dump(topo_data, f, indent=2)
    
    return topo_data


def print_topology_summary(topo_data):
    """
    Print a human-readable summary of the topology.
    
    Args:
        topo_data: Dictionary with topology data
    """
    print("\n=== Topology Summary ===")
    
    if 'metadata' in topo_data:
        meta = topo_data['metadata']
        print(f"Source: {meta.get('exported_from', 'unknown')}")
        print(f"Routers: {meta.get('total_routers', 0)}")
        print(f"Switches: {meta.get('total_switches', 0)}")
    
    if 'routers' in topo_data:
        print("\nRouters:")
        for rname, rinfo in topo_data['routers'].items():
            links = list(rinfo['links'].keys())
            print(f"  {rname}: connected to {', '.join(links)}")
    
    if 'switches' in topo_data:
        print("\nSwitches:")
        for sname, sinfo in topo_data['switches'].items():
            links = list(sinfo['links'].keys())
            print(f"  {sname}: connected to {', '.join(links)}")
    
    print("========================\n")


if __name__ == "__main__":
    print("This module should be imported, not run directly.")
    print("Use export_single_topo.py or export_all_topologies.py instead.")
