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
import logging
from collections import OrderedDict
from lib.topogen import TopoSwitch, TopoRouter

logger = logging.getLogger(__name__)


def export_topology_to_json(tgen, output_path=None):
    """
    Exports the current topology to a simplified JSON format:
    {
        "router_name": ["switch_name1", "switch_name2"],
        ...
    }
    
    Args:
        tgen (Topogen): The topogen instance with built topology
        output_path (str, optional): Path to save the JSON file
    
    Returns:
        dict: The topology dictionary
    """
    routers = tgen.routers()
    switches = tgen.get_gears(TopoSwitch)
    
    # Result dictionary: router -> list of connected switches
    simple_topo = {}
    
    # Initialize all routers in the dict
    for rname in routers:
        simple_topo[rname] = []

    # Map switches to routers by looking at links
    # Iterate over switches and find which routers they connect to
    for sname, switch in switches.items():
        for link_interface in switch.links:
            # switch.links[iface] = (peer_gear, peer_iface)
            peer_gear, _ = switch.links[link_interface]
            
            if isinstance(peer_gear, TopoRouter):
                # Found a connection from Switch -> Router
                rname = peer_gear.name
                if rname in simple_topo:
                    if sname not in simple_topo[rname]:
                        simple_topo[rname].append(sname)
                else:
                    # Should not happen if tgen.routers() covers everything, but safety first
                    simple_topo[rname] = [sname]
    
    # Sort lists for deterministic output
    for rname in simple_topo:
        simple_topo[rname].sort()

    # Sort keys
    sorted_topo = OrderedDict(sorted(simple_topo.items()))

    if output_path:
        try:
            with open(output_path, 'w') as f:
                json.dump(sorted_topo, f, indent=2)
            logger.info(f"Topology exported to {output_path}")
        except Exception as e:
            logger.error(f"Failed to export topology: {e}")
            
    return sorted_topo

def print_topology_summary(topo_data):
    """
    Print a summary of the simplified topology data.
    """
    print(f"\n=== Topology Summary ({len(topo_data)} routers) ===")
    
    for router, switches in topo_data.items():
        switches_str = ", ".join(switches) if switches else "None"
        print(f"  {router}: [{switches_str}]")
    
    print("========================\n")


if __name__ == "__main__":
    print("This module should be imported, not run directly.")
    print("Use export_single_topo.py or export_all_topologies.py instead.")
